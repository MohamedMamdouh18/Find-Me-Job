import streamlit as st

import library
from api import add_manual_job
from components.jobs_filters import render_jobs_filters
from components.jobs_list import invalidate_jobs_cache, render_jobs_list
from components.ui import page_header, summary_line
from constants import MATCH_CUTOFF, USER_STATUSES, USER_STATUS_LABELS


@st.dialog("Add job", width="small")
def _add_job_dialog():
    st.caption("Manually tracked jobs skip scraping and scoring and land straight in your list.")

    # Widget state cannot be reassigned once the widget exists in the same run, so
    # the fields are emptied by moving to a new set of keys instead of clearing them.
    n = st.session_state.get("mj_nonce", 0)

    title = st.text_input("Job title *", placeholder="Software Engineer", key=f"mj_title_{n}")
    company = st.text_input("Company *", placeholder="Acme Corp", key=f"mj_company_{n}")

    c1, c2 = st.columns(2)
    with c1:
        location = st.text_input("Location", placeholder="Remote", key=f"mj_location_{n}")
    with c2:
        status = st.selectbox(
            "Application status",
            USER_STATUSES,
            key=f"mj_status_{n}",
            format_func=lambda s: USER_STATUS_LABELS.get(s, s.title()),
        )

    applylink = st.text_input("Application link", placeholder="https://…", key=f"mj_link_{n}")
    easy_apply = st.checkbox("Easy Apply", key=f"mj_easy_{n}")
    description = st.text_area(
        "Notes or description", placeholder="Optional", key=f"mj_description_{n}", height=100
    )

    cancel_col, add_col = st.columns(2)
    if cancel_col.button("Cancel", width="stretch", key=f"mj_cancel_{n}"):
        st.rerun()

    if add_col.button("Add job", width="stretch", type="primary", key=f"mj_submit_{n}"):
        if not title.strip() or not company.strip():
            st.error("Title and company are required.")
            return
        ok = add_manual_job(
            title=title.strip(),
            company=company.strip(),
            location=location.strip() or "N/A",
            applylink=applylink.strip(),
            description=description.strip() or "Added manually via the dashboard",
            easy_apply=easy_apply,
            user_status=status,
        )
        if not ok:
            st.error("Could not add the job. Is the API reachable?")
            return
        st.session_state["mj_nonce"] = n + 1
        invalidate_jobs_cache()
        st.session_state["jobs_flash"] = f"Added {company.strip()} — {title.strip()}."
        st.rerun()


def render_jobs_tab():
    (add_col,) = page_header(
        "Jobs", "Everything the pipeline matched, and where each one stands.", actions=1, action_width=1.5
    )
    with add_col:
        if st.button("Add job", width="stretch", type="primary", icon=":material/add:", key="jobs_add"):
            _add_job_dialog()

    counts = library.stats()
    summary_line(
        [
            (counts["total"], "scored"),
            (counts["matched"], "matched"),
            (counts["strong"], "strong"),
            (counts["new"], "new"),
        ],
        trailing=f"matched means scored {MATCH_CUTOFF} or above",
    )

    toast = st.session_state.pop("job_toast", None)
    if toast:
        st.toast(toast, icon="✅")

    flash = st.session_state.pop("jobs_flash", None)
    if flash:
        st.success(flash)

    filters = render_jobs_filters(counts)
    render_jobs_list(filters, counts["total"])
