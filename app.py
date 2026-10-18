"""コンテンツ記録。起動: python -m streamlit run app.py"""
from copy import deepcopy
from datetime import date
from uuid import uuid4
import streamlit as st

import external_api
import stats
import storage
from components import bottom_navigation, navigate, record_card
from domain import CATEGORIES, PERIODS, record_date, today
from icons import icon


# 映像の数量欄の初期値。この値のままなら、作品検索の結果で上書きしてよい。
VIDEO_DEFAULTS = {"movie": {"minutes": 120}, "anime": {"episodes": 1, "minutes_per_episode": 24},
                  "drama": {"episodes": 1, "minutes_per_episode": 45}}
VIDEO_CREDITS = {
    "TMDB": "This product uses the TMDB API but is not endorsed or certified by TMDB. 作品情報: [TMDB](https://www.themoviedb.org/)",
    "Annict": "作品情報: [Annict](https://annict.com/)",
}


def open_record(record_id):
    navigate("detail", selected_record=record_id, return_page=st.session_state.get("page", "home"))


def start_entry(record=None, copy=False):
    st.session_state.pop("draft_upload", None)
    st.session_state.pop("isbn_result", None)
    st.session_state.pop("video_results", None)
    draft = deepcopy(record or {"category": "book", "metrics": {}, "image": {"type": "none", "value": None}})
    if copy:
        draft = storage.copy_record_data(record["id"])
        draft["recorded_on"] = today().isoformat()
    draft.setdefault("recorded_on", record_date(record) if record else today().isoformat())
    st.session_state["draft"] = draft
    st.session_state["draft_token"] = uuid4().hex
    st.session_state["draft_metrics"] = {draft["category"]: deepcopy(draft.get("metrics", {}))}
    st.session_state["copy_image"] = deepcopy(draft.get("image")) if copy else None
    st.session_state["draft_tags"] = {
        kind: [t["name"] for t in storage.load_tags(kind=kind) if t["id"] in draft.get("tag_ids", [])]
        for kind in ("genre", "emotion")}
    navigate("entry")


def home(records):
    st.title("コンテンツ記録")
    if not records:
        st.info("まだ記録がありません。下部の羽ペン「記録」から、最初の記録を残せます。")
        with st.expander("サンプルで画面を確認する"):
            st.caption("サンプルは実際の記録とは区別して、空の状態にだけ追加できます。")
            if st.button("サンプル記録を読み込む"):
                storage.load_demo()
                st.rerun()
        return
    # 長い履歴でも過去へ段階的にアクセスできる。
    ordered = [r for group in stats.grouped_records(records).values() for r in group]
    limit = st.session_state.get("home_limit", 20)
    for day, group in stats.grouped_records(ordered[:limit]).items():
        st.subheader(f"{day.replace('-', '/')}の記録")
        for record in group:
            record_card(record, open_record)
    if len(ordered) > limit and st.button("さらに記録を見る"):
        st.session_state["home_limit"] = limit + 20
        st.rerun()


def period_picker():
    return st.selectbox("期間", list(PERIODS), format_func=PERIODS.get, key="period")


def statistics(records):
    st.title("記録の集計")
    period = period_picker()
    settings = storage.load_settings()
    modes = {"amount": "量", "count": "数"}
    mode = st.segmented_control("表示", list(modes), format_func=modes.get,
                                default=settings.get("metric_mode", "amount"), key="metric_mode") or "amount"
    if mode != settings.get("metric_mode"):
        storage.save_settings({**settings, "metric_mode": mode})
    st.subheader("カテゴリ別の集計")
    summary = stats.category_summary(records, period, mode)
    # 幅が狭いと自然に折り返す。画面幅を取得するJSは不要。
    with st.container(horizontal=True, wrap=True, gap="small"):
        for row in summary.to_dict("records"):
            with st.container(width=280, border=True):
                st.image(icon(row["category"]), width=36)
                st.subheader(row["label"])
                if row["category"] == "other":
                    st.caption("数・量の集計対象外")
                    st.caption(f"{row['records']}件の記録")
                else:
                    st.metric("集計", f"{row['value']:,} {row['unit']}", label_visibility="collapsed")
                    if mode == "count" and row["category"] in ("anime", "drama"):
                        st.caption(f"{row['episodes']:,}話")
                    if mode == "count" and row["in_progress"]:
                        st.caption(f"途中の記録{row['in_progress']}件は読了数に含みません。")
                    if row["missing"]:
                        st.caption(f"値が未入力の記録が{row['missing']}件あります。")
                st.button("記録を見る ›", key=f"category_{row['category']}", width="stretch",
                          on_click=navigate, args=("category",), kwargs={"category": row["category"]})
    st.caption("カテゴリを選ぶと記録の詳細を表示します。単位の異なる量は合算しません。")


def category_detail(records):
    st.button("‹ 集計", on_click=navigate, args=("stats",))
    category = st.session_state.get("category", "book")
    st.title(f"{CATEGORIES[category]}の記録")
    period = st.session_state.get("period", "this_year")
    st.caption(f"{PERIODS[period]}" + ("・読んだページ数／総ページ数" if category in ("book", "manga") else ""))
    selected = [r for r in stats.filter_period(records, period) if r["category"] == category]
    if not selected:
        st.info("この期間には記録がありません。")
        return
    for group in stats.grouped_records(selected).values():
        for record in group:
            record_card(record, open_record, detailed=True)
    if category != "other":
        with st.expander("月別の集計を見る"):
            mode = st.session_state.get("metric_mode") or storage.load_settings().get("metric_mode", "amount")
            st.caption(f"単位：{stats.metric_unit(category, mode)}")
            st.bar_chart(stats.monthly_category(records, category, period, mode), color="#258B8B")


def search(records):
    st.title("記録を検索")
    query = st.text_input("タイトル・感想・作品情報", key="search_query")
    categories = st.multiselect("カテゴリ", list(CATEGORIES), format_func=CATEGORIES.get, key="search_categories")
    tags = storage.load_tags()
    tag_map = {t["id"]: f"{t['name']}（{'ジャンル' if t['kind'] == 'genre' else '感情'}）" for t in tags}
    selected_tags = st.multiselect("タグ（すべてを含む）", list(tag_map), format_func=tag_map.get, key="search_tags")
    date_range = st.date_input("記録日の範囲（任意）", value=[], key="search_dates")
    start = date_range[0] if date_range else None
    end = date_range[-1] if len(date_range) == 2 else None
    matches = stats.search_records(records, query, categories, selected_tags, start, end)
    st.caption(f"{len(matches)}件の記録")
    st.button("絞り込みを解除", on_click=clear_search)
    if not matches:
        st.info("条件に合う記録がありません。")
    for day, group in stats.grouped_records(matches).items():
        st.subheader(f"{day.replace('-', '/')}の記録")
        for record in group:
            record_card(record, open_record)


def clear_search():
    for key in ("search_query", "search_categories", "search_tags", "search_dates"):
        st.session_state.pop(key, None)


def entry():
    if "draft" not in st.session_state:
        start_entry()
    draft = st.session_state["draft"]
    token = st.session_state["draft_token"]
    def key(field):
        return f"entry_{token}_{field}"
    st.button("‹ 戻る（下書きを保持）", on_click=navigate, args=("home",))
    st.title("記録を編集" if draft.get("id") else "記録")
    draft["category"] = st.selectbox("カテゴリ", list(CATEGORIES), index=list(CATEGORIES).index(draft["category"]),
                                     format_func=CATEGORIES.get, key=key("category"))
    category = draft["category"]
    metrics = st.session_state["draft_metrics"].setdefault(category, {})
    if category in ("book", "manga"):
        with st.expander("ISBNから入力（任意）"):
            draft["isbn"] = st.text_input("ISBN-13", value=draft.get("isbn") or "", key=key("isbn"))
            if st.button("書誌情報を取得", key=key("lookup")):
                with st.spinner("書誌情報を取得しています…"):
                    result = external_api.lookup_isbn(draft["isbn"])
                if result:
                    st.session_state["isbn_result"] = result
                else:
                    st.info("取得できませんでした。そのまま手入力できます。")
            result = st.session_state.get("isbn_result")
            if result:
                st.write(result.get("title") or "タイトル未取得")
                if st.button("空欄に反映", key=key("apply_isbn")):
                    for field in ("title", "creator", "publisher"):
                        if not draft.get(field) and result.get(field):
                            draft[field] = result[field]
                            st.session_state[key(field)] = result[field]
                    if draft.get("image", {}).get("type", "none") == "none" and result.get("image_url"):
                        draft["image"] = {"type": "url", "value": result["image_url"]}
                    st.session_state.pop("isbn_result", None)
                    st.rerun()
    if category in VIDEO_DEFAULTS:
        video_lookup(draft, category, metrics, key)
    uploaded = st.file_uploader("カバー画像（任意）", type=["jpg", "jpeg", "png", "webp"], key=key("upload"))
    upload_error = None
    if uploaded is not None:
        # 読めないファイルを下書きに残すと、プレビューで毎回エラーになり入力画面が使えなくなる。
        try:
            st.session_state["draft_upload"] = storage.check_image(uploaded)
        except ValueError as exc:
            upload_error = str(exc)
            st.session_state.pop("draft_upload", None)
            st.error(upload_error)
    if st.session_state.get("draft_upload"):
        st.image(st.session_state["draft_upload"], width=90)
    else:
        path = storage.image_path(draft.get("image"))
        if path:
            st.image(str(path), width=90)
    remove_image = st.checkbox("カバー画像を外す", key=key("remove_image"))
    draft["title"] = st.text_input("タイトル", value=draft.get("title", ""), key=key("title"))
    day = st.date_input("記録日", value=date.fromisoformat(draft["recorded_on"]), key=key("day"))
    draft["recorded_on"] = day.isoformat()
    if category in ("book", "manga"):
        pages = st.number_input("読んだページ数" + ("（未入力可）" if category == "manga" else ""), min_value=0,
                                value=metrics.get("pages", 0) if category == "book" else metrics.get("pages"),
                                step=1, key=key(f"{category}_pages"))
        metrics["pages"] = pages
        metrics["total_pages"] = st.number_input("総ページ数（任意・進捗バーの基準）", min_value=1,
                                                 value=metrics.get("total_pages"), step=1, key=key(f"{category}_total"))
        if metrics.get("total_pages"):
            st.caption("総ページ数に達していない記録は「途中」として保存します。進捗は同じ記録を編集して更新してください。")
        if category == "manga":
            metrics["volumes"] = st.number_input("巻数（未入力可）", min_value=1, value=metrics.get("volumes"), step=1, key=key("volumes"))
    elif category == "movie":
        metrics["minutes"] = st.number_input("上映時間（分）", min_value=1, value=metrics.get("minutes", VIDEO_DEFAULTS["movie"]["minutes"]), step=1, key=key("minutes"))
    elif category in ("anime", "drama"):
        metrics["episodes"] = st.number_input("話数", min_value=1, value=metrics.get("episodes", VIDEO_DEFAULTS[category]["episodes"]), step=1, key=key(f"{category}_episodes"))
        metrics["minutes_per_episode"] = st.number_input("1話あたりの分数", min_value=1,
                                                        value=metrics.get("minutes_per_episode", VIDEO_DEFAULTS[category]["minutes_per_episode"]),
                                                        step=1, key=key(f"{category}_minutes"))
    draft["review"] = st.text_area("感想（任意）", value=draft.get("review", ""), key=key("review"))
    for kind, label in (("genre", "ジャンル"), ("emotion", "感情")):
        choices = [t["name"] for t in storage.load_tags(category=category, kind=kind)]
        selected = st.session_state["draft_tags"].get(kind, [])
        options = list(dict.fromkeys(choices + selected))
        st.session_state["draft_tags"][kind] = st.multiselect(f"{label}（任意）", options, default=selected,
                                                            accept_new_options=True, key=key(f"{kind}_{category}"))
    with st.expander("作品情報（任意）"):
        draft["creator"] = st.text_input("作者・監督など", value=draft.get("creator") or "", key=key("creator"))
        fields = ["publisher"] if category == "book" else (["publisher", "magazine"] if category == "manga" else (["studio"] if category in ("anime", "movie", "drama") else []))
        for field in fields:
            labels = {"publisher": "出版社", "magazine": "掲載誌", "studio": "制作会社"}
            candidates = list(dict.fromkeys(([draft[field]] if draft.get(field) else []) + storage.list_field_values(field, category)))
            draft[field] = st.selectbox(labels[field], candidates, index=0 if draft.get(field) else None,
                                        accept_new_options=True, placeholder="入力または候補から選択", key=key(field))
    if st.button("保存", type="primary", width="stretch", key=key("save")):
        payload = deepcopy(draft)
        payload["metrics"] = deepcopy(metrics)
        image_upload = st.session_state.get("draft_upload")
        if remove_image:
            payload["image"] = {"type": "none", "value": None}
            image_upload = None
        elif st.session_state.get("copy_image") and image_upload is None:
            source = storage.image_path(st.session_state["copy_image"])
            if source:
                image_upload = source.read_bytes()
        try:
            if upload_error and not remove_image:
                raise ValueError(upload_error)
            kwargs = dict(uploaded_file=image_upload, tag_names=st.session_state["draft_tags"])
            if draft.get("id"):
                saved = storage.update_record(draft["id"], payload, expected_updated_at=draft.get("updated_at"), **kwargs)
            else:
                saved = storage.add_record(payload, **kwargs)
        except (ValueError, OSError) as exc:
            st.error(str(exc))
        else:
            for field in ("draft", "draft_token", "draft_metrics", "draft_tags", "draft_upload", "copy_image", "isbn_result", "video_results"):
                st.session_state.pop(field, None)
            navigate("detail", selected_record=saved, return_page="home")
            st.session_state["flash"] = "記録を保存しました。"
            st.rerun()
    st.button("キャンセル（下書きを保持）", width="stretch", on_click=navigate, args=("home",), key=key("cancel"))


def video_lookup(draft, category, metrics, key):
    """作品名からTMDB／Annictで検索し、空欄と初期値のままの数量欄だけを埋める。"""
    with st.expander("作品名から入力（任意）"):
        missing = external_api.missing_video_keys(category)
        if missing:
            st.caption(f"検索には .streamlit/secrets.toml に {' または '.join(missing)} の設定が必要です。手入力はそのままできます。")
        query = st.text_input("作品名", value=draft.get("title", ""), key=key("video_query"))
        if st.button("作品を検索", key=key("video_search")):
            with st.spinner("作品を検索しています…"):
                results = external_api.search_video(query, category)
            st.session_state["video_results"] = {"category": category, "items": results or []}
            if results is None:
                st.info("検索できませんでした。キーの設定か通信を確認してください。そのまま手入力できます。")
            elif not results:
                st.info("見つかりませんでした。別の表記で検索するか、そのまま手入力できます。")
        found = st.session_state.get("video_results")
        if not found or found["category"] != category or not found["items"]:
            return
        items = found["items"]
        def label(index):
            year = str(items[index].get("release_date") or "")[:4]
            return items[index]["title"] + (f"（{year}）" if year.isdigit() else "")
        index = st.selectbox("検索結果", range(len(items)), format_func=label, key=key(f"video_pick_{category}"))
        st.caption(VIDEO_CREDITS[items[index]["source"]])
        if st.button("入力欄に反映", key=key("apply_video")):
            with st.spinner("作品情報を取得しています…"):
                result = external_api.video_details(items[index])
            for field in ("title", "creator", "studio"):
                if not draft.get(field) and result.get(field):
                    draft[field] = result[field]
                    st.session_state[key(field)] = result[field]
            widget_keys = {"minutes": "minutes", "episodes": f"{category}_episodes",
                           "minutes_per_episode": f"{category}_minutes"}
            for name, default in VIDEO_DEFAULTS[category].items():
                value = result["metrics"].get(name)
                if value and metrics.get(name, default) == default:
                    metrics[name] = value
                    st.session_state[key(widget_keys[name])] = value
            if draft.get("image", {}).get("type", "none") == "none" and result.get("image_url"):
                draft["image"] = {"type": "url", "value": result["image_url"]}
            st.session_state.pop("video_results", None)
            st.rerun()


def detail(records):
    record = next((r for r in records if r["id"] == st.session_state.get("selected_record")), None)
    st.button("‹ 戻る", on_click=navigate, args=(st.session_state.get("return_page", "home"),))
    if not record:
        st.info("記録が見つかりません。削除された可能性があります。")
        return
    st.title(record["title"])
    st.caption(f"{CATEGORIES[record['category']]}・{record_date(record).replace('-', '/')}")
    view = stats.record_view(record)
    if view["progress"] is not None:
        st.progress(view["progress"])
    with st.container(horizontal=True, horizontal_alignment="right"):
        st.caption(view["text"], width="content")
    if record.get("review"):
        st.text(record["review"])
    for field, label in (("creator", "作者・監督など"), ("publisher", "出版社"), ("magazine", "掲載誌"), ("studio", "制作会社"), ("isbn", "ISBN")):
        if record.get(field):
            st.text(f"{label}：{record[field]}")
    tags = [t["name"] for t in storage.load_tags() if t["id"] in record.get("tag_ids", [])]
    if tags:
        st.text("タグ：" + " / ".join(tags))
    st.button("編集", on_click=start_entry, args=(record,))
    st.button("コピーして新しい記録を作る", on_click=start_entry, args=(record, True))
    with st.expander("この記録を削除"):
        confirmed = st.checkbox("この記録とカバー画像を削除する", key=f"confirm_{record['id']}")
        if st.button("削除を実行", disabled=not confirmed):
            storage.delete_record(record["id"])
            navigate("home")
            st.rerun()


def tag_management():
    st.title("タグ管理")
    st.caption("名前変更・削除・統合は、関連する記録にも反映されます。")
    kind = st.radio("種類", ["genre", "emotion"], format_func=lambda k: "ジャンル" if k == "genre" else "感情", horizontal=True)
    tags = storage.load_tags(kind=kind)
    with st.expander("タグを追加"):
        name = st.text_input("新しいタグ名")
        cats = st.multiselect("表示カテゴリ", ["all", *CATEGORIES], default=["all"], format_func=lambda k: "すべて" if k == "all" else CATEGORIES[k])
        if st.button("タグを追加する"):
            storage.add_tag(name, kind, cats)
            st.rerun()
    if not tags:
        st.info("この種類のタグはありません。")
        return
    by_id = {t["id"]: t for t in tags}
    selected = st.selectbox("編集するタグ", list(by_id), format_func=lambda k: by_id[k]["name"])
    tag = by_id[selected]
    name = st.text_input("名前", value=tag["name"], key=f"tag_name_{selected}")
    color = st.color_picker("色", value=tag["color"], key=f"tag_color_{selected}")
    cats = st.multiselect("表示するカテゴリ", ["all", *CATEGORIES], default=tag["categories"],
                         format_func=lambda k: "すべて" if k == "all" else CATEGORIES[k], key=f"tag_cats_{selected}")
    if st.button("変更を保存"):
        storage.update_tag(selected, name, color, cats)
        st.rerun()
    with st.expander("削除・統合"):
        targets = [t["id"] for t in tags if t["id"] != selected]
        target = st.selectbox("統合先", targets, index=None, format_func=lambda k: by_id[k]["name"])
        confirm = st.checkbox("関連する記録のタグも変更することを確認しました")
        if st.button("選んだタグへ統合", disabled=not confirm or target is None):
            storage.merge_tags(selected, target)
            st.rerun()
        if st.button("タグを削除", disabled=not confirm):
            storage.delete_tag(selected)
            st.rerun()


def main():
    st.set_page_config(page_title="コンテンツ記録", page_icon="📖", layout="centered")
    if not hasattr(st, "bottom"):
        st.error("固定ナビゲーションにはStreamlit 1.66.0が必要です。requirements.txtのバージョンで起動してください。")
        st.stop()
    try:
        # キーを環境変数にも展開させる（external_apiはStreamlitに依存しない）。
        st.secrets.load_if_toml_exists()
    except Exception:
        pass
    st.session_state.setdefault("page", "home")
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    try:
        records = storage.load_records()
        page = st.session_state["page"]
        {"home": lambda: home(records), "entry": entry, "stats": lambda: statistics(records),
         "category": lambda: category_detail(records), "search": lambda: search(records),
         "detail": lambda: detail(records), "tags": tag_management}.get(page, lambda: home(records))()
        if page not in ("entry", "tags"):
            with st.expander("管理"):
                st.button("タグ管理を開く", on_click=navigate, args=("tags",))
        if page == "tags":
            st.button("ホームへ戻る", on_click=navigate, args=("home",))
        bottom_navigation()
    except (ValueError, OSError) as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
