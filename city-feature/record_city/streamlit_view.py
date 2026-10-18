"""Optional thin adapter. Never sets page config, navigation, CSS, or session state."""
from .config import load_config
from .core import calculate_city
from .render import render_html

# The host can append this item to its existing four-item navigation.
CITY_NAV_ITEM = ("city", "街")


def render_city(amounts, *, config=None, theme="auto", show_summary=True):
    """Call inside the host's city route/container with already aggregated amounts."""
    import streamlit as st
    config = config or load_config()
    state = calculate_city(amounts, config)
    st.html(render_html(state, config, theme=theme, show_summary=show_summary, image_mode=True))
    return state
