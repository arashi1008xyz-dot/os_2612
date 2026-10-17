from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

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

    def test_isbn_checksum(self):
        self.assertEqual(external_api.normalize_isbn("978-4-10-101001-4"), "9784101010014")
        with self.assertRaises(ValueError):
            external_api.normalize_isbn("9784101010015")

    def test_demo_load_only_into_empty_records(self):
        storage.load_demo()
        self.assertEqual(len(storage.load_records()), 9)
        with self.assertRaises(ValueError):
            storage.load_demo()


if __name__ == "__main__":
    unittest.main()
