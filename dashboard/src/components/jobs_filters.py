import os

import streamlit as st
from api import get_filter_options
from constants import AI_STATUSES, USER_STATUSES, SK_PAGE

DEFAULT_MIN_SCORE = int(os.getenv("FILTERING_SCORE", "60"))

_DEFAULTS = {
    "search_input": "",
    "min_score_slider": DEFAULT_MIN_SCORE,
    "min_score_input": DEFAULT_MIN_SCORE,
    "page_size_select": 20,
    "ai_status_select": "fit",
    "user_status_select": "new",
    "easy_apply_select": "all",
    "company_select": "all",
    "website_select": "all",
    "location_select": "all",
    "sort_by_select": "updated_at",
    "sort_order_select": "desc",
    "starred_only_check": False,
}


def _none_if_all(value: str) -> str | None:
    return None if value == "all" else value


def _init_defaults():
    for key, val in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _clear_filters():
    for key, val in _DEFAULTS.items():
        st.session_state[key] = val
    st.session_state[SK_PAGE] = 1


def _on_ai_status_change():
    if st.session_state.ai_status_select != "all":
        st.session_state.min_score_slider = 0
        st.session_state.min_score_input = 0


def _on_score_slider_change():
    st.session_state.min_score_input = st.session_state.min_score_slider
    if st.session_state.min_score_slider > 0:
        st.session_state.ai_status_select = "all"


def _on_score_input_change():
    val = max(0, min(100, st.session_state.min_score_input))
    st.session_state.min_score_input = val
    st.session_state.min_score_slider = val
    if val > 0:
        st.session_state.ai_status_select = "all"


@st.cache_data(ttl=300)
def _get_cached_filter_options() -> dict:
    return get_filter_options()


def render_jobs_filters() -> dict:
    options = _get_cached_filter_options()
    companies = ["all"] + options.get("companies", [])
    websites = ["all"] + options.get("websites", [])
    locations = ["all"] + options.get("locations", [])

    _init_defaults()

    # Row 1: search + score slider/input + clear + per page + starred
    s1, s2, s3, s4, s5, s6 = st.columns([3, 2, 0.6, 0.8, 0.7, 0.9])
    with s1:
        search = st.text_input(
            "Search", key="search_input", label_visibility="collapsed",
            placeholder="Search by title, company, or location...",
        )
    with s2:
        min_score = st.slider(
            "Min Score", 0, 100,
            key="min_score_slider", on_change=_on_score_slider_change,
        )
    with s3:
        st.number_input(
            "Score", 0, 100, step=1,
            key="min_score_input", on_change=_on_score_input_change,
        )
    with s4:
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        st.button("Clear Filters", on_click=_clear_filters, use_container_width=True)
    with s5:
        page_size = st.selectbox("Per page", [10, 20, 50, 100], key="page_size_select")
    with s6:
        st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
        starred_only = st.checkbox("⭐ Starred only", key="starred_only_check")

    # Row 2: main filters
    f1, f2, f3, f4, f5, f6, f7, f8 = st.columns(8)
    with f1:
        ai_status_raw = st.selectbox(
            "AI Status", ["all"] + AI_STATUSES,
            key="ai_status_select", on_change=_on_ai_status_change,
        )
    with f2:
        user_status_raw = st.selectbox(
            "User Status", ["all"] + USER_STATUSES,
            key="user_status_select",
        )
    with f3:
        easy_apply_raw = st.selectbox("Easy Apply", ["all", "yes", "no"], key="easy_apply_select")
    with f4:
        company_raw = st.selectbox("Company", companies, key="company_select")
    with f5:
        website_raw = st.selectbox("Website", websites, key="website_select")
    with f6:
        location_raw = st.selectbox("Country", locations, key="location_select")
    with f7:
        sort_by = st.selectbox(
            "Sort By", ["updated_at", "score", "title", "company", "created_at"],
            key="sort_by_select",
        )
    with f8:
        sort_order = st.selectbox("Order", ["desc", "asc"], key="sort_order_select")

    return {
        "ai_status": _none_if_all(ai_status_raw),
        "user_status": _none_if_all(user_status_raw),
        "easy_apply": True if easy_apply_raw == "yes" else False if easy_apply_raw == "no" else None,
        "min_score": min_score,
        "search": search.strip() or None,
        "company": _none_if_all(company_raw),
        "website": _none_if_all(website_raw),
        "location": _none_if_all(location_raw),
        "starred_only": starred_only,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "page_size": page_size,
    }
