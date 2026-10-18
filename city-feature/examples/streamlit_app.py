"""Integration harness only. The feature itself owns neither input nor navigation."""
import streamlit as st
from record_city import RecordAmounts
from record_city.streamlit_view import render_city

st.set_page_config(page_title="街づくり・単体確認", page_icon="🏙️", layout="centered")
with st.expander("単体確認用の記録量を指定する"):
    book = st.number_input("本（ページ）",min_value=0,value=6000)
    manga = st.number_input("漫画（ページ）",min_value=0,value=24000)
    anime = st.number_input("アニメ（分）",min_value=0,value=2400)
    movie = st.number_input("映画（分）",min_value=0,value=1800)
    drama = st.number_input("ドラマ（分）",min_value=0,value=3330)
render_city(RecordAmounts(book,manga,anime,movie,drama))
