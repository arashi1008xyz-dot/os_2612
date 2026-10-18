from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image
import external_api
import stats
import storage
from domain import pages_progress


def book(pages=300, total=500, **extra):
    return dict(category="book", title="テストの本", recorded_on="2026-10-16",
                metrics={"pages": pages, "total_pages": total}, **extra)


class CoreTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parent / ".scratch"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.original = storage.DATA_DIR
        storage.DATA_DIR = Path(self.temp.name)

    def tearDown(self):
        storage.DATA_DIR = self.original
        self.temp.cleanup()

    def test_roundtrip_japanese_and_partial_date(self):
        record_id = storage.add_record(book(review="感想を残す"))
        record = storage.get_record(record_id)
        self.assertEqual(record["review"], "感想を残す")
        self.assertEqual(record["status"], "in_progress")
        self.assertIsNone(record["finished_on"])
        self.assertEqual(record["recorded_on"], "2026-10-16")
        self.assertEqual(pages_progress(record), 0.6)

    def test_progress_is_individual_denominator(self):
        self.assertEqual(pages_progress(book(300, 500)), 0.6)
        self.assertEqual(pages_progress(book(300, 300)), 1)
        self.assertEqual(pages_progress(book(0, 300)), 0)

    def test_unknown_total_is_not_completion_bar(self):
        data = book()
        del data["metrics"]["total_pages"]
        record = storage.validate(data)
        self.assertIsNone(pages_progress(record))
        self.assertIsNone(stats.record_view(record)["progress"])

    def test_invalid_pages_do_not_write(self):
        for data in (book(501, 500), book(-1, 500), book(3.5, 500), book(True, 500), book(1, 0)):
            with self.assertRaises(ValueError):
                storage.add_record(data)
        self.assertEqual(storage.load_records(), [])

    def test_title_and_date_validation(self):
        for field, value in (("title", "　 "), ("recorded_on", "not-a-date"), ("category", "unknown")):
            data = book()
            data[field] = value
            with self.assertRaises(ValueError):
                storage.add_record(data)

    def test_same_title_does_not_merge(self):
        first = storage.add_record(book())
        second = storage.add_record(book())
        self.assertNotEqual(first, second)
        self.assertEqual(len(storage.load_records()), 2)

    def test_edit_does_not_double_count(self):
        record_id = storage.add_record(book())
        storage.update_record(record_id, book(400, 500))
        self.assertEqual(len(storage.load_records()), 1)
        result = stats.category_summary(storage.load_records(), "all", "amount")
        self.assertEqual(result.loc[result.category == "book", "value"].iloc[0], 400)

    def test_stale_edit_is_rejected(self):
        record_id = storage.add_record(book())
        old = storage.get_record(record_id)
        storage.update_record(record_id, book(400, 500))
        with self.assertRaises(ValueError):
            storage.update_record(record_id, book(), expected_updated_at=old["updated_at"])

    def test_completed_count_excludes_partial(self):
        storage.add_record(book())
        storage.add_record(book(500, 500))
        result = stats.category_summary(storage.load_records(), "all", "count")
        row = result.loc[result.category == "book"].iloc[0]
        self.assertEqual(row["value"], 1)
        self.assertEqual(row["records"], 2)

    def test_all_categories_and_units(self):
        inputs = [book(),
                  dict(category="manga", metrics={"volumes":2}),
                  dict(category="movie", metrics={"minutes":124}),
                  dict(category="anime", metrics={"episodes":12,"minutes_per_episode":24}),
                  dict(category="drama", metrics={"episodes":6,"minutes_per_episode":45}),
                  dict(category="other", metrics={})]
        for data in inputs:
            data.setdefault("title", "作品")
            data.setdefault("recorded_on", "2026-10-16")
            storage.add_record(data)
        result = stats.category_summary(storage.load_records(), "all", "amount").set_index("category")
        self.assertEqual(result.loc["anime", "value"], 288)
        self.assertEqual(result.loc["drama", "value"], 270)
        self.assertEqual(result.loc["manga", "missing"], 1)
        self.assertEqual(result.loc["other", "records"], 1)
        self.assertEqual(result.loc["other", "unit"], "")
        self.assertEqual(result.loc["book", "unit"], "ページ")
        self.assertEqual(result.loc["movie", "unit"], "分")

    def test_manga_requires_one_metric(self):
        with self.assertRaises(ValueError):
            storage.add_record(dict(category="manga", title="漫画", recorded_on="2026-10-16", metrics={}))

    def test_partial_manga_does_not_count_as_finished_volume(self):
        record = storage.validate(dict(category="manga", title="漫画", recorded_on="2026-10-16",
                                       metrics={"pages":50,"total_pages":100,"volumes":1}))
        self.assertEqual(stats.metric_value(record, "count"), 0)
        self.assertEqual(stats.metric_value(record, "amount"), 50)

    def test_period_boundaries(self):
        records = [dict(id=day, recorded_on=day) for day in ("2025-10-31", "2025-11-01", "2026-01-01", "2026-10-17", "2026-10-18")]
        selected = stats.filter_period(records, "last_12_months", date(2026,10,17))
        self.assertEqual([r["id"] for r in selected], ["2025-11-01", "2026-01-01", "2026-10-17"])

    def test_monthly_empty_months_and_partial_amount(self):
        records = [storage.validate(book())]
        frame = stats.monthly_category(records, "book", "this_year", "amount", date(2026,10,17))
        self.assertEqual(len(frame), 10)
        self.assertEqual(frame.loc["2026-09", "ページ"], 0)
        self.assertEqual(frame.loc["2026-10", "ページ"], 300)

    def test_tag_normalization_and_separate_kind(self):
        first = storage.add_tag(" ＳＦ ", "genre", ["book"])
        second = storage.add_tag("SF", "genre", ["manga"])
        emotion = storage.add_tag("SF", "emotion", ["all"])
        self.assertEqual(first, second)
        self.assertNotEqual(first, emotion)
        self.assertIn("manga", storage.load_tags(category="manga")[0]["categories"])

    def test_tag_merge_and_delete_references(self):
        source = storage.add_tag("元", "genre", ["book"])
        target = storage.add_tag("先", "genre", ["manga"])
        record_id = storage.add_record(book(tag_ids=[source, target]))
        storage.merge_tags(source, target)
        self.assertEqual(storage.get_record(record_id)["tag_ids"], [target])
        self.assertEqual(len(storage.load_tags()), 1)
        storage.delete_tag(target)
        self.assertEqual(storage.get_record(record_id)["tag_ids"], [])

    def test_cross_kind_merge_rejected(self):
        source = storage.add_tag("元", "genre", ["all"])
        target = storage.add_tag("先", "emotion", ["all"])
        with self.assertRaises(ValueError):
            storage.merge_tags(source, target)

    def test_image_copy_is_independent(self):
        out = BytesIO()
        Image.new("RGB", (30,40), "red").save(out, format="PNG")
        original = storage.add_record(book(), uploaded_file=out.getvalue())
        copied = storage.add_record(storage.copy_record_data(original))
        source_path = storage.image_path(storage.get_record(original)["image"])
        copy_path = storage.image_path(storage.get_record(copied)["image"])
        self.assertNotEqual(source_path, copy_path)
        storage.delete_record(original)
        self.assertTrue(copy_path.exists())
        self.assertFalse(source_path.exists())

    def test_invalid_image_does_not_add_record(self):
        with self.assertRaises(ValueError):
            storage.add_record(book(), uploaded_file=b"not-an-image")
        self.assertEqual(storage.load_records(), [])

    def test_path_traversal_image_rejected(self):
        self.assertIsNone(storage.image_path({"type":"upload", "value":"../settings.json"}))

    def test_search_unicode_and_tags(self):
        tag = storage.add_tag("SF", "genre", ["all"])
        storage.add_record(book(review="ＳＦの物語", tag_ids=[tag]))
        result = stats.search_records(storage.load_records(), query="sf", tag_ids=[tag])
        self.assertEqual(len(result), 1)

    def test_corrupt_json_is_not_overwritten(self):
        path = storage.DATA_DIR / "records.json"
        path.write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            storage.add_record(book())
        self.assertEqual(path.read_text(encoding="utf-8"), "broken")

    def test_concurrent_adds_do_not_lose_records(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: storage.add_record(book()), range(12)))
        self.assertEqual(len(set(ids)), 12)
        self.assertEqual(len(storage.load_records()), 12)

    def test_settings_roundtrip(self):
        storage.save_settings({"metric_mode":"count"})
        self.assertEqual(storage.load_settings()["metric_mode"], "count")

    def test_display_settings_defaults_and_validation(self):
        self.assertEqual((storage.load_settings()["font"], storage.load_settings()["font_size"]), ("biz_ud_gothic", "normal"))
        storage.save_settings({**storage.load_settings(), "font": "biz_ud_mincho", "font_size": "xlarge"})
        self.assertEqual(storage.load_settings()["font_size"], "xlarge")
        with self.assertRaises(ValueError):
            storage.save_settings({**storage.load_settings(), "font_size": "huge"})

    def test_plain_markdown_keeps_title_text(self):
        import components
        self.assertEqual(components.plain_markdown("a*b_[x](y) #1"), r"a\*b\_\[x\]\(y\) \#1")

    def test_isbn_checksum(self):
        self.assertEqual(external_api.normalize_isbn("978-4-10-101001-4"), "9784101010014")
        with self.assertRaises(ValueError):
            external_api.normalize_isbn("9784101010015")

    def test_video_search_without_keys_returns_none(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(external_api.search_video("君の名は", "movie"))
            self.assertEqual(external_api.missing_video_keys("anime"), ["ANNICT_ACCESS_TOKEN", "TMDB_API_READ_ACCESS_TOKEN"])

    def test_tmdb_movie_details_map_to_metrics(self):
        responses = [
            {"results": [{"id": 1, "title": "テスト映画", "release_date": "2016-08-26", "poster_path": "/p.jpg"}]},
            {"title": "テスト映画", "runtime": 107, "poster_path": "/p.jpg",
             "production_companies": [{"name": "制作A"}], "credits": {"crew": [{"job": "Director", "name": "監督A"}]}},
        ]
        with mock.patch.dict("os.environ", {"TMDB_API_READ_ACCESS_TOKEN": "t"}, clear=True), \
                mock.patch.object(external_api, "_get_json", side_effect=responses):
            item = external_api.search_video("テスト", "movie")[0]
            details = external_api.video_details(item)
        self.assertEqual(details["metrics"], {"minutes": 107})
        self.assertEqual((details["creator"], details["studio"]), ("監督A", "制作A"))
        self.assertTrue(details["image_url"].startswith("https://"))

    def test_anime_falls_back_to_tmdb_and_details_survive_errors(self):
        responses = [{"works": []}, {"results": [{"id": 2, "name": "テストアニメ"}]}]
        env = {"ANNICT_ACCESS_TOKEN": "a", "TMDB_API_READ_ACCESS_TOKEN": "t"}
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch.object(external_api, "_get_json", side_effect=responses):
            item = external_api.search_video("テスト", "anime")[0]
        self.assertEqual(item["source"], "TMDB")
        with mock.patch.object(external_api, "_get_json", side_effect=OSError):
            self.assertEqual(external_api.video_details(item), item)

    def test_annict_details_use_staff_roles(self):
        responses = [
            {"works": [{"id": 3, "title": "テストアニメ", "episodes_count": 12, "images": {"recommended_url": "http://x"}}]},
            {"staffs": [{"role_text": "監督", "name": "監督B"}, {"role_text": "アニメーション制作", "name": "スタジオB"}]},
        ]
        with mock.patch.dict("os.environ", {"ANNICT_ACCESS_TOKEN": "a"}, clear=True), \
                mock.patch.object(external_api, "_get_json", side_effect=responses):
            item = external_api.search_video("テスト", "anime")[0]
            details = external_api.video_details(item)
        self.assertIsNone(item["image_url"])
        self.assertEqual(details["metrics"]["episodes"], 12)
        self.assertEqual((details["creator"], details["studio"]), ("監督B", "スタジオB"))

    def test_demo_load_only_into_empty_records(self):
        storage.load_demo()
        self.assertEqual(len(storage.load_records()), 9)
        with self.assertRaises(ValueError):
            storage.load_demo()


if __name__ == "__main__":
    unittest.main()
