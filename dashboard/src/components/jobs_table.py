import streamlit as st
import pandas as pd
from api import get_filtered_jobs
from components.job_card import render_job_card
from constants import SK_PAGE, SK_FILTER_KEY, SK_SELECTED_JOB_INDEX


def _reset_page_on_filter_change(filters: dict):
    filter_key = str(filters)
    if SK_FILTER_KEY not in st.session_state or st.session_state[SK_FILTER_KEY] != filter_key:
        st.session_state[SK_PAGE] = 1
        st.session_state[SK_FILTER_KEY] = filter_key
        st.session_state[SK_SELECTED_JOB_INDEX] = None


def render_jobs_table(filters: dict):
    if SK_PAGE not in st.session_state:
        st.session_state[SK_PAGE] = 1

    page_size = filters["page_size"]
    _reset_page_on_filter_change(filters)

    resp = get_filtered_jobs(
        ai_status=filters["ai_status"],
        user_status=filters["user_status"],
        easy_apply=filters["easy_apply"],
        min_score=filters["min_score"],
        search=filters["search"],
        company=filters["company"],
        website=filters["website"],
        location=filters["location"],
        sort_by=filters["sort_by"],
        sort_order=filters["sort_order"],
        page=st.session_state[SK_PAGE],
        page_size=page_size,
    )

    jobs = resp.get("rows", [])
    total_jobs = resp.get("total", 0)
    total_pages = resp.get("pages", 1)

    st.markdown(
        f'<div class="section-title">Jobs — {total_jobs} results</div>',
        unsafe_allow_html=True,
    )

    if not jobs:
        st.info("No jobs found matching your filters.")
        return

    df = pd.DataFrame(
        [
            {
                "Title": j["title"],
                "Company": j["company"],
                "Location": j.get("location", "N/A"),
                "Website": j["website"],
                "Easy Apply": "✅" if j.get("easy_apply") else "❌",
                "Apply": j.get("applylink", ""),
                "Score": j["score"],
            }
            for j in jobs
        ]
    )

    has_selection = st.session_state.get(SK_SELECTED_JOB_INDEX) is not None

    if has_selection:
        table_col, card_col = st.columns([3, 2])
    else:
        table_col = st.container()
        card_col = None

    with table_col:
        dynamic_height = (len(df) + 1) * 35 + 3
        event = st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=dynamic_height,
            on_select="rerun",
            selection_mode="single-row",
            key="jobs_dataframe",
            column_config={
                "Apply": st.column_config.LinkColumn("Apply", display_text="🔗 Link"),
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
            },
        )

    selected_rows = []
    if event:
        selection = event.get("selection", {})  # type: ignore[union-attr]
        selected_rows = selection.get("rows", []) if selection else []

    prev_index = st.session_state.get(SK_SELECTED_JOB_INDEX)

    if selected_rows:
        new_index = selected_rows[0]
        if prev_index != new_index:
            st.session_state[SK_SELECTED_JOB_INDEX] = new_index
            st.rerun()
    elif prev_index is not None:
        st.session_state[SK_SELECTED_JOB_INDEX] = None
        st.rerun()

    selected_index = st.session_state.get(SK_SELECTED_JOB_INDEX)
    if card_col and selected_index is not None and selected_index < len(jobs):
        with card_col:
            render_job_card(jobs[selected_index])

    _render_pagination(total_pages)


def _render_pagination(total_pages: int):
    if total_pages <= 1:
        return

    st.write("")
    p1, p2, p3 = st.columns([1, 3, 1])

    with p1:
        if st.button("← Prev", disabled=st.session_state[SK_PAGE] <= 1, use_container_width=True):
            st.session_state[SK_PAGE] -= 1
            st.rerun()

    with p2:
        st.markdown(
            f'<div class="pagination-text">'
            f"Page {st.session_state[SK_PAGE]} of {total_pages}</div>",
            unsafe_allow_html=True,
        )

    with p3:
        if st.button(
            "Next →",
            disabled=st.session_state[SK_PAGE] >= total_pages,
            use_container_width=True,
        ):
            st.session_state[SK_PAGE] += 1
            st.rerun()
