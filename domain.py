"""画面と保存処理の双方で用いる定義。Streamlitには依存しない。"""
from datetime import datetime, timedelta, timezone

CATEGORIES = {
    "book": "本", "manga": "漫画", "anime": "アニメ",
    "movie": "映画", "drama": "ドラマ", "other": "その他",
}
PERIODS = {"this_year": "今年", "last_12_months": "過去12か月", "all": "全期間"}
JST = timezone(timedelta(hours=9))


def today():
    return datetime.now(JST).date()


def record_date(record):
    return record.get("recorded_on") or record.get("finished_on") or record["created_at"][:10]


def pages_progress(record):
    """不明な総ページ数をゼロや読了と推測しない。"""
    metrics = record.get("metrics", {})
    pages, total = metrics.get("pages"), metrics.get("total_pages")
    if pages is None or total is None or total <= 0:
        return None
    return pages / total


def completed(record):
    return record.get("status", "completed") == "completed"
