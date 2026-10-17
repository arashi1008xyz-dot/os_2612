"""JSON の読み書き・入力チェック・正規化（仕様書 v0.4 §6, §11）。

このファイル以外から data/ の JSON を直接触らない。
"""

import json
import os
import tempfile
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RECORDS_PATH = DATA_DIR / "records.json"
IMAGES_DIR = DATA_DIR / "images"

JST = timezone(timedelta(hours=9))

CATEGORIES = ("book", "manga", "anime", "movie", "drama", "other")

# 作品の項目・ISBN を持てるカテゴリ（それ以外は null にする）
FIELD_CATEGORIES = {
    "publisher": {"book", "manga"},
    "magazine": {"manga"},
    "studio": {"movie", "anime", "drama"},
    "isbn": {"book", "manga"},
}

DEFAULT_MINUTES_PER_EPISODE = {"anime": 24, "drama": 45}

IMAGE_TYPES = ("url", "upload", "none")

# 入力として受け付けるキー。id・日時はストレージ側で付けるので、渡されても無視する
INPUT_KEYS = {
    "category", "title", "creator", "publisher", "magazine", "studio", "isbn",
    "image", "tag_ids", "rating", "review", "finished_on", "metrics",
}
IGNORED_KEYS = {"id", "created_at", "updated_at"}


# ---------- 記録 ----------

def load_records() -> list[dict]:
    """全記録を返す。ファイルが無ければ空のリスト。"""
    return _read_json(RECORDS_PATH, default=[])


def get_record(record_id) -> dict | None:
    """id が一致する記録を 1 件返す。無ければ None。"""
    for record in load_records():
        if record["id"] == record_id:
            return record
    return None


def add_record(data: dict) -> str:
    """入力チェック・正規化をして、id・日時を付けて保存し、id を返す。

    ルール違反は ValueError。
    """
    record = _validate_record(data)
    now = _now()
    record = {"id": str(uuid.uuid4()), **record, "created_at": now, "updated_at": now}

    records = load_records()
    records.append(record)
    _write_json(RECORDS_PATH, records)
    return record["id"]


def update_record(record_id, data: dict) -> None:
    """記録を更新する。data に含めた項目だけ上書きし、全体を入力チェックし直す。

    ルール違反は ValueError、記録が無ければ KeyError。
    """
    records = load_records()
    index = _find_index(records, record_id)
    current = records[index]

    merged = {key: value for key, value in current.items() if key in INPUT_KEYS}
    merged.update(data)
    record = _validate_record(merged)

    records[index] = {
        "id": current["id"],
        **record,
        "created_at": current["created_at"],
        "updated_at": _now(),
    }
    _write_json(RECORDS_PATH, records)


def delete_record(record_id) -> None:
    """記録を削除する。アップロード画像があれば一緒に削除する。

    記録が無ければ KeyError。
    """
    records = load_records()
    index = _find_index(records, record_id)
    record = records.pop(index)
    _write_json(RECORDS_PATH, records)
    _delete_uploaded_image(record.get("image"))


# ---------- 正規化 ----------

def normalize_text(value) -> str | None:
    """全角・半角をそろえ（NFKC）、前後の空白を取る。空なら None。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"文字列を入力してください（{value!r}）")
    value = unicodedata.normalize("NFKC", value).strip()
    return value or None


# ---------- 入力チェック ----------

def _validate_record(data: dict) -> dict:
    """入力をチェック・正規化して、保存する形の dict（id・日時なし）を返す。"""
    if not isinstance(data, dict):
        raise ValueError("記録のデータは dict で渡してください")
    unknown = set(data) - INPUT_KEYS - IGNORED_KEYS
    if unknown:
        raise ValueError(f"不明な項目があります: {', '.join(sorted(unknown))}")

    category = data.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"カテゴリが正しくありません（{category!r}）")

    title = normalize_text(data.get("title"))
    if title is None:
        raise ValueError("タイトルを入力してください")

    fields = {}
    for field, allowed in FIELD_CATEGORIES.items():
        if category not in allowed:
            fields[field] = None
        elif field == "isbn":
            fields[field] = _validate_isbn(data.get("isbn"))
        else:
            fields[field] = normalize_text(data.get(field))

    return {
        "category": category,
        "title": title,
        "creator": normalize_text(data.get("creator")),
        "publisher": fields["publisher"],
        "magazine": fields["magazine"],
        "studio": fields["studio"],
        "isbn": fields["isbn"],
        "image": _validate_image(data.get("image")),
        "tag_ids": _validate_tag_ids(data.get("tag_ids")),
        "rating": _validate_rating(data.get("rating")),
        "review": _normalize_review(data.get("review")),
        "finished_on": _validate_date(data.get("finished_on")),
        "metrics": _validate_metrics(category, data.get("metrics")),
    }


def _validate_metrics(category: str, metrics) -> dict:
    if metrics is None:
        metrics = {}
    if not isinstance(metrics, dict):
        raise ValueError("metrics は dict で渡してください")

    if category == "book":
        return _pick_positive_ints(metrics, ["pages"])

    if category == "manga":
        result = _pick_positive_ints(metrics, ["pages", "volumes"])
        if not result:
            raise ValueError("漫画はページ数か巻数の少なくとも一方を入力してください")
        return result

    if category == "movie":
        return _pick_positive_ints(metrics, ["minutes"])

    if category in ("anime", "drama"):
        result = _pick_positive_ints(metrics, ["episodes", "minutes_per_episode"])
        result.setdefault("minutes_per_episode", DEFAULT_MINUTES_PER_EPISODE[category])
        return result

    return {}  # other は集計しないので空


def _pick_positive_ints(metrics: dict, keys: list[str]) -> dict:
    """keys のうち値が入っているものを正の整数にして返す（未入力のものは含めない）。"""
    labels = {
        "pages": "ページ数",
        "volumes": "巻数",
        "minutes": "上映時間",
        "episodes": "話数",
        "minutes_per_episode": "1 話あたりの分数",
    }
    result = {}
    for key in keys:
        value = metrics.get(key)
        if value is None or value == "":
            continue
        # st.number_input は float を返すことがあるので、整数値の float は受け付ける
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{labels[key]}は 1 以上の整数で入力してください（{value!r}）")
        result[key] = value
    return result


def _validate_isbn(value) -> str | None:
    value = normalize_text(value)
    if value is None:
        return None
    isbn = value.replace("-", "").replace(" ", "")
    if len(isbn) != 13 or not isbn.isdigit() or not isbn.startswith(("978", "979")):
        raise ValueError(f"ISBN は 978 / 979 で始まる 13 桁で入力してください（{value}）")
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn[:12]))
    if (10 - total % 10) % 10 != int(isbn[12]):
        raise ValueError(f"ISBN のチェックディジットが正しくありません（{value}）")
    return isbn


def _validate_image(image) -> dict:
    if image is None:
        return {"type": "none", "value": None}
    if not isinstance(image, dict) or image.get("type") not in IMAGE_TYPES:
        raise ValueError("画像の type は url / upload / none のいずれかにしてください")
    if image["type"] == "none":
        return {"type": "none", "value": None}
    value = image.get("value")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("画像の URL またはファイルパスを指定してください")
    return {"type": image["type"], "value": value.strip()}


def _validate_tag_ids(tag_ids) -> list[str]:
    if tag_ids is None:
        return []
    if not isinstance(tag_ids, (list, tuple)) or not all(isinstance(t, str) for t in tag_ids):
        raise ValueError("tag_ids は文字列のリストで渡してください")
    return list(dict.fromkeys(tag_ids))  # 順番を保って重複を除く


def _validate_rating(rating) -> int | None:
    if rating is None:
        return None
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ValueError(f"評価は 1〜5 の整数で入力してください（{rating!r}）")
    return rating


def _normalize_review(review) -> str | None:
    """感想は改行を残したいので、前後の空白を取るだけにする。"""
    if review is None:
        return None
    if not isinstance(review, str):
        raise ValueError("感想は文字列で入力してください")
    return review.strip() or None


def _validate_date(value) -> str:
    if value is None or value == "":
        raise ValueError("読了日・視聴完了日を入力してください")
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            pass
    raise ValueError(f"日付は YYYY-MM-DD の形で入力してください（{value!r}）")


# ---------- 内部処理 ----------

def _find_index(records: list[dict], record_id) -> int:
    for i, record in enumerate(records):
        if record["id"] == record_id:
            return i
    raise KeyError(f"記録が見つかりません（{record_id}）")


def _delete_uploaded_image(image) -> None:
    """data/images/ の中にあるアップロード画像だけを削除する。"""
    if not image or image.get("type") != "upload" or not image.get("value"):
        return
    path = Path(image["value"])
    if not path.is_absolute():
        path = BASE_DIR / path
    path = path.resolve()
    if path.is_relative_to(IMAGES_DIR.resolve()) and path.is_file():
        path.unlink()


def _now() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def _read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data) -> None:
    """一時ファイルに書いてから置き換える（書き込み途中で落ちても壊れないように）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
