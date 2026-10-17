"""表示部品。数量・進捗はstatsの戻り値を表示する。"""
import streamlit as st
import storage
from domain import CATEGORIES, record_date
from icons import button_label, icon
from stats import record_view


def navigate(page, **values):
    st.session_state["page"] = page
    st.session_state.update(values)


def bottom_navigation():
    active = st.session_state.get("page", "home")
    if active == "entry":
        return
    with st.bottom:
        # 横並びコンテナでスマホでも4列を維持。独自CSSは不要。
        with st.container(horizontal=True, wrap=False, gap="xsmall"):
            for page, label in (("home", "ホーム"), ("entry", "記録"), ("stats", "集計"), ("search", "検索")):
                selected = active == page or (page == "stats" and active == "category")
                image_name = "record" if page == "entry" else page
                st.button(button_label(image_name, label), key=f"nav_{page}",
                          type="primary" if selected else "tertiary", width="stretch",
                          on_click=navigate, args=(page,))


def record_card(record, on_open, detailed=False):
    with st.container(border=False):
        with st.container(horizontal=True, wrap=False, gap="small"):
            with st.container(width=70):
                image = record.get("image", {})
                source = storage.image_path(image)
                if source:
                    st.image(str(source), width=65)
                elif image.get("type") == "url" and str(image.get("value", "")).startswith("https://"):
                    # 外部表紙が消えた場合もタイトルとカテゴリから記録を判別できる。
                    st.image(image["value"], width=65)
                else:
                    st.image(icon(record["category"]), width=56)
            with st.container(width="stretch"):
                st.button(record["title"], key=f"open_{record['id']}", type="tertiary",
                          width="stretch", on_click=on_open, args=(record["id"],))
                view = record_view(record)
                if detailed:
                    st.caption(record_date(record).replace("-", "/"))
                    if view["progress"] is not None:
                        st.progress(view["progress"])
                    with st.container(horizontal=True, horizontal_alignment="right"):
                        st.caption(view["text"], width="content")
                    if record["category"] in ("book", "manga") and view["progress"] is None:
                        st.caption("総ページ数未登録のため、進捗バーは表示していません。")
                else:
                    st.caption(f"{CATEGORIES[record['category']]}　{view['text']}")
                if record.get("review"):
                    # textは入力内のMarkdownやHTMLを解釈しない。
                    st.text(record["review"])
        st.divider()
