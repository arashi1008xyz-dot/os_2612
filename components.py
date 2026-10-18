"""表示部品。数量・進捗はstatsの戻り値を表示する。"""
import re
import streamlit as st
import storage
from domain import CATEGORIES, FONT_SIZES, FONTS, record_date
from icons import button_label, icon
from stats import record_view


def navigate(page, **values):
    st.session_state["page"] = page
    st.session_state.update(values)


GOOGLE_FONTS = "https://fonts.googleapis.com/css2?family=BIZ+UDPGothic:wght@400;700&family=BIZ+UDPMincho:wght@400;700&display=swap"


def apply_display_settings(settings):
    """文字の大きさとフォントを画面全体に反映する。

    Streamlitには画面から全体の文字を切り替える機能がないため、ここだけCSSを使う（仕様の例外）。
    文字の大きさは基準（rem）を変えるので、見出しなども同じ比率で変わる。アイコンのフォントは変えない。
    """
    size = FONT_SIZES[settings["font_size"]][1]
    family = FONTS[settings["font"]][1]
    st.html(f"<style>@import url('{GOOGLE_FONTS}');"
            f"html {{ font-size: {size} !important; }}"
            f".stApp, .stApp *:not([data-testid='stIconMaterial']) {{ font-family: {family} !important; }}</style>")


def plain_markdown(text):
    """記録のタイトルなどをMarkdownとして解釈させずにそのまま表示する。"""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|~<>:$])", r"\\\1", str(text))


def bottom_navigation():
    active = st.session_state.get("page", "home")
    if active == "entry":
        return
    with st.bottom:
        # 横並びコンテナでスマホでも5列を維持。独自CSSは不要。
        with st.container(horizontal=True, wrap=False, gap="xsmall"):
            for page, label in (("home", "ホーム"), ("entry", "記録"), ("stats", "集計"), ("search", "検索"), ("city", "街")):
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
                # ボタンの文字は大きくできないため、タイトルは見出し（h5）で表示し、詳細は下のボタンで開く。
                st.markdown(f"##### {plain_markdown(record['title'])}", anchors=False)
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
                st.button("詳細 ›", key=f"open_{record['id']}", type="tertiary",
                          on_click=on_open, args=(record["id"],))
        st.divider()
