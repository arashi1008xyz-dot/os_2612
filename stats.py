"""表示用集計。記録のロード、保存、画面描画は行わない。"""
from datetime import date
import pandas as pd
from domain import CATEGORIES, completed, pages_progress, record_date, today


def filter_period(records, period, as_of=None):
    end = as_of or today()
    if period == "all":
        return list(records)
    if period == "this_year":
        start = date(end.year, 1, 1)
    elif period == "last_12_months":
        # 今月を含む12暦月。未来の記録は含めない。
        month_index = end.year * 12 + end.month - 12
        year, month = divmod(month_index, 12)
        start = date(year, month + 1, 1)
    else:
        raise ValueError("期間が正しくありません。")
    return [r for r in records if start <= date.fromisoformat(record_date(r)) <= end]


def grouped_records(records):
    groups = {}
    for record in sorted(records, key=lambda r: (record_date(r), r.get("created_at", "")), reverse=True):
        groups.setdefault(record_date(record), []).append(record)
    return groups


def metric_value(record, mode):
    category, m = record["category"], record.get("metrics", {})
    if category == "other":
        return None
    if mode == "count":
        if category == "manga":
            volumes = m.get("volumes")
            return volumes if completed(record) or volumes is None else 0
        return int(completed(record))
    if category in ("book", "manga"):
        return m.get("pages")
    if category == "movie":
        return m.get("minutes")
    episodes, minutes = m.get("episodes"), m.get("minutes_per_episode")
    return episodes * minutes if episodes is not None and minutes is not None else None


def metric_unit(category, mode):
    if category == "other":
        return ""
    if mode == "amount":
        return "ページ" if category in ("book", "manga") else "分"
    return {"book": "冊", "manga": "巻", "movie": "本", "anime": "作品", "drama": "作品"}[category]


def category_summary(records, period, mode, as_of=None):
    selected = filter_period(records, period, as_of)
    rows = []
    for category, label in CATEGORIES.items():
        group = [r for r in selected if r["category"] == category]
        values = [metric_value(r, mode) for r in group]
        rows.append(dict(category=category, label=label, records=len(group),
                         value=sum(v for v in values if v is not None), unit=metric_unit(category, mode),
                         missing=sum(v is None for v in values) if category != "other" else 0,
                         episodes=sum(r.get("metrics", {}).get("episodes", 0) for r in group),
                         in_progress=sum(not completed(r) for r in group)))
    return pd.DataFrame(rows)


def record_view(record):
    """表示する数量・進捗はここで計算。総ページ数不明ならバーを作らない。"""
    m, category = record.get("metrics", {}), record["category"]
    if category in ("book", "manga"):
        pages, total = m.get("pages"), m.get("total_pages")
        text = f"{pages:,}／{total:,}ページ" if pages is not None and total else (f"{pages:,}ページ" if pages is not None else "ページ数未入力")
        if category == "manga" and m.get("volumes") is not None:
            text += f"・{m['volumes']}巻"
        return dict(text=text, progress=pages_progress(record))
    value = metric_value(record, "amount")
    text = "" if value is None else f"{value:,}分"
    if category in ("anime", "drama"):
        text = f"{m.get('episodes', 0)}話・{text}"
    return dict(text=text, progress=None)


def search_records(records, query="", categories=None, tag_ids=None, start=None, end=None):
    from storage import normalize
    query = normalize(query).casefold()
    def matches(record):
        day = date.fromisoformat(record_date(record))
        text = normalize(" ".join(str(record.get(k) or "") for k in ("title", "review", "creator", "publisher", "magazine", "studio"))).casefold()
        return ((not query or query in text) and (not categories or record["category"] in categories)
                and (not tag_ids or set(tag_ids).issubset(record.get("tag_ids", [])))
                and (not start or day >= start) and (not end or day <= end))
    return [r for r in records if matches(r)]


def monthly_category(records, category, period, mode, as_of=None):
    selected = filter_period(records, period, as_of)
    selected = [r for r in selected if r["category"] == category]
    end = as_of or today()
    if period == "this_year":
        start = date(end.year, 1, 1)
    elif period == "last_12_months":
        idx = end.year * 12 + end.month - 12
        y, m = divmod(idx, 12)
        start = date(y, m + 1, 1)
    elif selected:
        start = min(date.fromisoformat(record_date(r)).replace(day=1) for r in selected)
        end = max(end, max(date.fromisoformat(record_date(r)) for r in selected))
    else:
        start = end.replace(day=1)
    months = pd.period_range(start, end, freq="M").astype(str)
    totals = {month: 0 for month in months}
    for r in selected:
        value = metric_value(r, mode)
        if value is not None:
            totals[record_date(r)[:7]] += value
    return pd.DataFrame({"月": list(totals), metric_unit(category, mode): list(totals.values())}).set_index("月")


def count_by_category(records, period):
    frame = category_summary(records, period, "count")
    return frame[["category", "label", "records"]].rename(columns={"records": "count"})


def count_by_tag(records, tags, period):
    selected = filter_period(records, period)
    return pd.DataFrame([dict(tag_id=t["id"], name=t["name"], kind=t["kind"],
                              count=sum(t["id"] in r.get("tag_ids", []) for r in selected))
                         for t in tags], columns=["tag_id", "name", "kind", "count"])


def this_month_summary(records):
    prefix = today().isoformat()[:7]
    selected = [r for r in records if record_date(r).startswith(prefix)]
    return {"records": len(selected),
            "pages": sum(metric_value(r, "amount") or 0 for r in selected if r["category"] in ("book", "manga")),
            "minutes": sum(metric_value(r, "amount") or 0 for r in selected if r["category"] in ("anime", "movie", "drama"))}
