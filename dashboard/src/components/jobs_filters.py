import os

import streamlit as st
from api import get_filter_options

DEFAULT_MIN_SCORE = int(os.getenv("FILTERING_SCORE", "60"))


def render_jobs_filters() -> dict:
    options = get_filter_options()
    companies = ["all"] + options.get("companies", [])
    websites = ["all"] + options.get("websites", [])
    locations = ["all"] + options.get("locations", [])

    # Row 1: search + per page
    s1, s2 = st.columns([5, 1])
    with s1:
        search = st.text_input("🔍 Search", key="search_input", label_visibility="collapsed",
                               placeholder="Search by title, company, or location...")
    with s2:
        page_size = st.selectbox("Per page", [10, 20, 50, 100], index=1, key="page_size_select")

    # Row 2: main filters
    f1, f2, f3, f4, f5, f6, f7, f8 = st.columns(8)
    with f1:
        user_status_raw = st.selectbox("User Status", ["all", "new", "applied", "wont_apply", "email_sent"], index=1)
    with f2:
        easy_apply_raw = st.selectbox("Easy Apply", ["all", "yes", "no"])
    with f3:
        min_score = st.slider("Min Score", 0, 100, DEFAULT_MIN_SCORE)
    with f4:
        company_raw = st.selectbox("Company", companies)
    with f5:
        website_raw = st.selectbox("Website", websites)
    with f6:
        location_raw = st.selectbox("Country", locations)
    with f7:
        sort_by = st.selectbox("Sort By", ["updated_at", "score", "title", "company", "created_at"])
    with f8:
        sort_order = st.selectbox("Order", ["desc", "asc"])

    return {
        "user_status": None if user_status_raw == "all" else user_status_raw,
        "easy_apply": True
        if easy_apply_raw == "yes"
        else False
        if easy_apply_raw == "no"
        else None,
        "min_score": min_score,
        "search": search.strip() or None,
        "company": None if company_raw == "all" else company_raw,
        "website": None if website_raw == "all" else website_raw,
        "location": None if location_raw == "all" else location_raw,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "page_size": page_size,
    }
