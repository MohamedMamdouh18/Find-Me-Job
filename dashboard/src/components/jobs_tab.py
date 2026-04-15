import streamlit as st
from api import add_manual_job
from constants import USER_STATUSES, USER_STATUS_LABELS
from components.jobs_filters import render_jobs_filters
from components.jobs_table import render_jobs_table


def _clear_manual_job_feedback():
    if "manual_job_feedback" in st.session_state:
        del st.session_state["manual_job_feedback"]


def render_jobs_tab():
    # ── Add Job Manually Section ──────────────────────────────────────────────
    # A collapsible form letting the user bypass the AI processing and queueing
    # by taking basic inputs to immediately persist standard jobs.
    with st.expander("➕ Add Job Manually", expanded=False):
        # Feedback label
        if "manual_job_feedback" in st.session_state:
            fb = st.session_state["manual_job_feedback"]
            color = "green" if fb["success"] else "red"
            st.markdown(
                f"<div style='color: {color}; margin-bottom: 10px;'>{fb['msg']}</div>",
                unsafe_allow_html=True,
            )

        mj_key = st.session_state.get("mj_form_key", 0)
        with st.container():
            col1, col2 = st.columns(2)
            with col1:
                title = st.text_input(
                    "Job Title *",
                    placeholder="Software Engineer",
                    key=f"mj_title_{mj_key}",
                    on_change=_clear_manual_job_feedback,
                )
                location = st.text_input(
                    "Location",
                    placeholder="Remote",
                    key=f"mj_location_{mj_key}",
                    on_change=_clear_manual_job_feedback,
                )
                status = st.selectbox(
                    "Status",
                    options=USER_STATUSES,
                    format_func=lambda x: USER_STATUS_LABELS.get(x, x.title()),
                    key=f"mj_status_{mj_key}",
                    on_change=_clear_manual_job_feedback,
                )
            with col2:
                company = st.text_input(
                    "Company *",
                    placeholder="Acme Corp",
                    key=f"mj_company_{mj_key}",
                    on_change=_clear_manual_job_feedback,
                )
                applylink = st.text_input(
                    "Application Link",
                    placeholder="https://...",
                    key=f"mj_applylink_{mj_key}",
                    on_change=_clear_manual_job_feedback,
                )

            easy_apply = st.checkbox(
                "Easy Apply", key=f"mj_easy_apply_{mj_key}", on_change=_clear_manual_job_feedback
            )
            description = st.text_area(
                "Job Description",
                placeholder="Brief description (optional)",
                key=f"mj_description_{mj_key}",
                on_change=_clear_manual_job_feedback,
            )

            submitted = st.button("Submit Job", use_container_width=True)

        if submitted:
            if not title.strip() or not company.strip():
                st.session_state["manual_job_feedback"] = {
                    "success": False,
                    "msg": "❌ Title and Company are required.",
                }
                st.rerun()
            else:
                success = add_manual_job(
                    title=title.strip(),
                    company=company.strip(),
                    location=location.strip() or "N/A",
                    applylink=applylink.strip(),
                    description=description.strip() or "Added manually via Dashboard",
                    easy_apply=easy_apply,
                    user_status=status,
                )
                if success:
                    st.session_state["manual_job_feedback"] = {
                        "success": True,
                        "msg": f"✅ Successfully added manual job at {company}!",
                    }
                    st.session_state["mj_form_key"] = mj_key + 1

                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.session_state["manual_job_feedback"] = {
                        "success": False,
                        "msg": "❌ Failed to add job.",
                    }
                    st.rerun()

    filters = render_jobs_filters()
    render_jobs_table(filters)
