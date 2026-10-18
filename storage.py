"""JSONと画像のI/Oをこのモジュールに集約する。"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unicodedata
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from domain import CATEGORIES, DEFAULT_SETTINGS, FONT_SIZES, FONTS, JST

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CONTENT_RECORDS_DATA_DIR", ROOT / "data"))


def normalize(value):
    return unicodedata.normalize("NFKC", str(value or "")).strip()


@contextmanager
def _locked():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR / "storage.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + 5
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise ValueError("保存処理が混み合っています。もう一度お試しください。")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read(name, default):
    path = DATA_DIR / name
    if not path.exists():
        return deepcopy(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"{name}を読み込めません。元ファイルは変更していません。") from exc
    if not isinstance(data, type(default)):
        raise ValueError(f"{name}のデータ形式が正しくありません。")
    return data


def _write(name, data):
    path = DATA_DIR / name
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def load_records():
    with _locked():
        return _read("records.json", [])


def get_record(record_id):
    return next((r for r in load_records() if r["id"] == record_id), None)


def load_settings():
    with _locked():
        # 項目が増える前のsettings.jsonでも、足りない項目は既定値で補う。
        return {**DEFAULT_SETTINGS, **_read("settings.json", {})}


def save_settings(settings):
    settings = {**DEFAULT_SETTINGS, **settings}
    if (settings.get("metric_mode") not in ("amount", "count") or settings.get("font") not in FONTS
            or settings.get("font_size") not in FONT_SIZES):
        raise ValueError("表示設定が正しくありません。")
    with _locked():
        _write("settings.json", settings)


def load_tags(category=None, kind=None):
    with _locked():
        tags = _read("tags.json", [])
    return [t for t in tags if (kind is None or t["kind"] == kind)
            and (category is None or "all" in t["categories"] or category in t["categories"])]


def _tag(tags, name, kind, categories, color="#258B8B"):
    name = normalize(name)
    if not name or kind not in ("genre", "emotion"):
        raise ValueError("タグ名と種類を指定してください。")
    if not categories or any(c not in (*CATEGORIES, "all") for c in categories):
        raise ValueError("タグの表示カテゴリを指定してください。")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("タグの色が正しくありません。")
    existing = next((t for t in tags if t["name"] == name and t["kind"] == kind), None)
    if existing:
        # 同名タグの新規選択カテゴリでも候補として再利用できるようにする。
        if "all" not in existing["categories"]:
            existing["categories"] = sorted(set(existing["categories"] + categories))
        return existing["id"]
    numbers = [int(t["id"][2:]) for t in tags if re.fullmatch(r"t-\d+", t["id"])]
    tag_id = f"t-{max(numbers, default=0) + 1:03d}"
    tags.append(dict(id=tag_id, name=name, kind=kind, categories=categories,
                     color=color, is_template=False))
    return tag_id


def add_tag(name, kind, categories, color="#258B8B"):
    with _locked():
        tags = _read("tags.json", [])
        tag_id = _tag(tags, name, kind, categories, color)
        _write("tags.json", tags)
        return tag_id


def _integer(value, label, optional=False, zero=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if zero else 1):
        raise ValueError(f"{label}は{'0以上' if zero else '1以上'}の整数で入力してください。")
    return value


def validate(data):
    record = deepcopy(data)
    category = record.get("category")
    if category not in CATEGORIES:
        raise ValueError("カテゴリを選択してください。")
    record["title"] = normalize(record.get("title"))
    if not record["title"]:
        raise ValueError("タイトルを入力してください。")
    try:
        day = date.fromisoformat(record.get("recorded_on") or record.get("finished_on", ""))
    except (ValueError, TypeError):
        raise ValueError("記録日を正しく入力してください。") from None
    record["recorded_on"] = day.isoformat()
    source = record.get("metrics", {})
    if not isinstance(source, dict):
        raise ValueError("数量の形式が正しくありません。")
    metrics = {}
    status = "completed"
    if category in ("book", "manga"):
        optional = category == "manga"
        metrics["pages"] = _integer(source.get("pages"), "読んだページ数", optional, zero=True)
        total = _integer(source.get("total_pages"), "総ページ数", optional=True)
        if total is not None:
            if metrics["pages"] is None or metrics["pages"] > total:
                raise ValueError("読んだページ数は総ページ数以下にしてください。")
            metrics["total_pages"] = total
            status = "completed" if metrics["pages"] == total else "in_progress"
        if category == "manga":
            metrics["volumes"] = _integer(source.get("volumes"), "巻数", optional=True)
            if metrics["pages"] is None and metrics["volumes"] is None:
                raise ValueError("漫画はページ数または巻数のどちらかを入力してください。")
    elif category == "movie":
        metrics["minutes"] = _integer(source.get("minutes"), "上映時間")
    elif category in ("anime", "drama"):
        metrics["episodes"] = _integer(source.get("episodes"), "話数")
        metrics["minutes_per_episode"] = _integer(source.get("minutes_per_episode"), "1話あたりの分数")
    record["metrics"] = {k: v for k, v in metrics.items() if v is not None}
    record["status"] = status
    record["finished_on"] = day.isoformat() if status == "completed" else None
    record["review"] = str(record.get("review") or "").strip()
    for field in ("creator", "publisher", "magazine", "studio", "isbn"):
        allowed = field == "creator" or (field in ("publisher", "isbn") and category in ("book", "manga")) or (field == "magazine" and category == "manga") or (field == "studio" and category in ("movie", "anime", "drama"))
        record[field] = (normalize(record.get(field)) or None) if allowed else None
    if record["isbn"]:
        from external_api import normalize_isbn
        record["isbn"] = normalize_isbn(record["isbn"])
    # 評価は画面にも新規保存データにも追加しない。旧データの値は保持する。
    return record


def check_image(upload):
    """選んだ時点で、保存時と同じ条件（10MB以下・画像として読める）を確かめる。満たさなければValueError。"""
    raw = upload.getvalue() if hasattr(upload, "getvalue") else upload
    if not isinstance(raw, bytes) or len(raw) > 10 * 1024 * 1024:
        raise ValueError("画像は10MB以下にしてください。")
    try:
        with Image.open(BytesIO(raw)) as source:
            source.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("画像を読み込めません。JPEG・PNG・WebPをお試しください。") from exc
    return raw


def _image_bytes(upload):
    raw = check_image(upload)
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > 25_000_000:
                raise ValueError("画像の解像度が大きすぎます。")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1200, 1600))
            out = BytesIO()
            image.save(out, format="JPEG", quality=88)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("画像を読み込めません。JPEG・PNG・WebPをお試しください。") from exc


def _store_image(record_id, content):
    folder = DATA_DIR / "images"
    folder.mkdir(exist_ok=True)
    name = f"{record_id}-{uuid4().hex}.jpg"
    (folder / name).write_bytes(content)
    return {"type": "upload", "value": f"images/{name}"}


def image_path(image):
    if not image or image.get("type") != "upload":
        return None
    path = (DATA_DIR / image.get("value", "")).resolve()
    folder = (DATA_DIR / "images").resolve()
    return path if path.is_relative_to(folder) and path.is_file() else None


def _remove_image(image):
    path = image_path(image)
    if path:
        path.unlink(missing_ok=True)


def _save(data, record_id=None, uploaded_file=None, tag_names=None, expected_updated_at=None):
    record = validate(data)
    image_content = _image_bytes(uploaded_file) if uploaded_file is not None else None
    with _locked():
        records = _read("records.json", [])
        old = next((r for r in records if r["id"] == record_id), None)
        if record_id and old is None:
            raise ValueError("この記録は見つかりません。")
        if old and expected_updated_at and old["updated_at"] != expected_updated_at:
            raise ValueError("別の画面で更新されています。記録を開き直してください。")
        now = datetime.now(JST).isoformat()
        record.update(id=record_id or str(uuid4()), created_at=old["created_at"] if old else now, updated_at=now)
        tags = _read("tags.json", [])
        tag_ids = list(dict.fromkeys(record.get("tag_ids", [])))
        if tag_names is not None:
            tag_ids = [_tag(tags, name, kind, [record["category"]])
                       for kind, names in tag_names.items() for name in names if normalize(name)]
        known = {t["id"] for t in tags}
        if any(t not in known for t in tag_ids):
            raise ValueError("選択したタグが削除されています。選び直してください。")
        record["tag_ids"] = list(dict.fromkeys(tag_ids))
        record["image"] = record.get("image") or {"type": "none", "value": None}
        new_image = None
        if image_content is None and old is None:
            source_path = image_path(record["image"])
            if source_path:
                image_content = source_path.read_bytes()
        if image_content:
            new_image = _store_image(record["id"], image_content)
            record["image"] = new_image
        try:
            # 新規タグを先に保存し、記録が未定義タグを参照する窓を作らない。
            _write("tags.json", tags)
            if old:
                records[records.index(old)] = record
            else:
                records.append(record)
            _write("records.json", records)
        except Exception:
            if new_image:
                _remove_image(new_image)
            raise
        if old and old.get("image") != record["image"]:
            _remove_image(old.get("image"))
        return record["id"]


def add_record(data, **kwargs):
    return _save(data, **kwargs)


def update_record(record_id, data, **kwargs):
    return _save(data, record_id=record_id, **kwargs)


def delete_record(record_id):
    with _locked():
        records = _read("records.json", [])
        old = next((r for r in records if r["id"] == record_id), None)
        _write("records.json", [r for r in records if r["id"] != record_id])
        if old:
            _remove_image(old.get("image"))


def copy_record_data(record_id):
    record = get_record(record_id)
    if not record:
        raise ValueError("記録が見つかりません。")
    for key in ("id", "created_at", "updated_at"):
        record.pop(key, None)
    # 保存前は元の画像をプレビュー。保存時に画像を独立したファイルへ複製する。
    record["review"] = ""
    return record


def list_field_values(field, category=None):
    if field not in ("publisher", "magazine", "studio"):
        raise ValueError("対象外の項目です。")
    counts = Counter(r.get(field) for r in load_records() if r.get(field) and (category is None or r["category"] == category))
    return [v for v, _ in counts.most_common()]


def update_tag(tag_id, name, color, categories):
    with _locked():
        tags = _read("tags.json", [])
        tag = next((t for t in tags if t["id"] == tag_id), None)
        if not tag:
            raise ValueError("タグが見つかりません。")
        name = normalize(name)
        if any(t["id"] != tag_id and t["kind"] == tag["kind"] and t["name"] == name for t in tags):
            raise ValueError("同名のタグがあります。統合を使用してください。")
        _tag([], name, tag["kind"], categories, color)  # 同じ検証を使う。
        tag.update(name=name, color=color, categories=categories)
        _write("tags.json", tags)


def _rewrite_tag(source_id, target_id=None):
    with _locked():
        tags = _read("tags.json", [])
        source = next((t for t in tags if t["id"] == source_id), None)
        target = next((t for t in tags if t["id"] == target_id), None)
        if not source or (target_id and (not target or target_id == source_id or target["kind"] != source["kind"])):
            raise ValueError("同じ種類の別のタグを統合先に選んでください。")
        records = _read("records.json", [])
        for record in records:
            ids = record.get("tag_ids", [])
            if source_id in ids:
                record["tag_ids"] = list(dict.fromkeys([t for t in ids if t != source_id] + ([target_id] if target_id else [])))
                record["updated_at"] = datetime.now(JST).isoformat()
        if target:
            target["categories"] = list(dict.fromkeys(target["categories"] + source["categories"]))
        _write("records.json", records)
        _write("tags.json", [t for t in tags if t["id"] != source_id])


def delete_tag(tag_id):
    _rewrite_tag(tag_id)


def merge_tags(source_id, target_id):
    _rewrite_tag(source_id, target_id)


def load_demo():
    """利用者が明示的に選んだときだけ、空の記録へ投入する。"""
    with _locked():
        if _read("records.json", []):
            raise ValueError("サンプルは記録が空のときだけ追加できます。")
        demo = json.loads((ROOT / "data" / "demo_records.json").read_text(encoding="utf-8"))
        records = []
        for data in demo:
            record = validate(data)
            now = datetime.now(JST).isoformat()
            record.update(id=str(uuid4()), created_at=now, updated_at=now,
                          tag_ids=[], image={"type": "none", "value": None})
            records.append(record)
        _write("records.json", records)
