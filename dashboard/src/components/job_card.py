import streamlit as st

from api import update_job_status, delete_job, get_job_history
from pdf import build_pdf
from constants import (
    AI_BADGE_CLASS,
    AI_NOT_FIT,
    USER_BADGE_CLASS,
    USER_NEW,
    USER_STATUSES,
    USER_STATUS_LABELS,
)


def _score_class(score: int) -> str:
    if score >= 70:
        return "score-high"
    elif score >= 50:
        return "score-mid"
    return "score-low"


def _badge(text: str, css_class: str) -> str:
    return f'<span class="badge {css_class}">{text}</span>'


def _format_history_timestamp(raw: str) -> str:
    return raw.replace("T", " ")[:16]


def render_job_card(job: dict):
    score = job.get("score", 0)
    ai_status = job.get("ai_status", "")
    user_status = job.get("user_status", USER_NEW)
    job_id = job.get("id")
    easy_apply = job.get("easy_apply", False)

    ai_badge = _badge(ai_status, AI_BADGE_CLASS.get(ai_status, AI_BADGE_CLASS[AI_NOT_FIT]))
    us_badge = _badge(
        USER_STATUS_LABELS.get(user_status, user_status),
        USER_BADGE_CLASS.get(user_status, USER_BADGE_CLASS[USER_NEW]),
    )
    easy_badge = _badge("Easy Apply", "badge-easy") if easy_apply else ""

    title = job.get("title", "N/A")
    company = job.get("company", "N/A")
    icon = "⚡" if easy_apply else "·"

    with st.expander(f"{icon} {title} — {company}", expanded=True):
        meta_col, action_col = st.columns([3, 2])

        with meta_col:
            st.markdown(
                f"""
            <div style="margin-bottom:0.5rem">
                <span class="{_score_class(score)}" style="font-size:1.4rem">{score}</span>
                <span style="opacity:0.5;font-size:0.8rem;margin-left:0.5rem">score</span>
            </div>
            <div style="opacity:0.7;font-size:0.85rem;margin-bottom:0.4rem">
                📍 {job.get("location", "N/A")} &nbsp;|&nbsp; 🌐 {job.get("website", "N/A")}
            </div>
            <div style="margin-top:0.4rem">
                {ai_badge}{us_badge}{easy_badge}
            </div>
            """,
                unsafe_allow_html=True,
            )

            st.markdown(f"🔗 [Apply Here]({job.get('applylink', '#')})")

        with action_col:
            st.markdown(
                '<div style="opacity:0.5;font-size:0.75rem;text-transform:uppercase;'
                'letter-spacing:0.1em;margin-bottom:0.5rem">Status</div>',
                unsafe_allow_html=True,
            )

            current_index = (
                USER_STATUSES.index(user_status) if user_status in USER_STATUSES else 0
            )
            selected = st.selectbox(
                "Status",
                USER_STATUSES,
                index=current_index,
                format_func=lambda s: USER_STATUS_LABELS.get(s, s),
                key=f"status_{job_id}",
                label_visibility="collapsed",
            )

            if selected != user_status:
                if st.button(
                    f"Update to {USER_STATUS_LABELS.get(selected, selected)}",
                    key=f"upd_{job_id}",
                    use_container_width=True,
                ):
                    update_job_status(job_id, selected)
                    st.rerun()

            if st.button(
                "🗑 Delete", key=f"delete_{job_id}", use_container_width=True, type="primary"
            ):
                delete_job(job_id)
                st.session_state.pop("selected_job", None)
                st.rerun()

        if job.get("description"):
            with st.expander("📄 Description"):
                st.write(job["description"])

        if job.get("application_document"):
            with st.expander("✉️ Application Document"):
                st.text_area(
                    "Application Document",
                    job["application_document"],
                    height=200,
                    key=f"cl_{job_id}",
                    label_visibility="collapsed",
                )
                pdf_bytes = build_pdf(job["application_document"], title, company)
                file_name = f"{title} - {company}.pdf".replace("/", "-")
                st.download_button(
                    "📥 Download as PDF",
                    data=pdf_bytes,
                    file_name=file_name,
                    mime="application/pdf",
                    key=f"pdf_{job_id}",
                    use_container_width=True,
                )

        with st.expander("📜 Status History"):
            history = get_job_history(job_id)
            if not history:
                st.caption("No transitions recorded")
            else:
                for row in history:
                    label = USER_STATUS_LABELS.get(row["status"], row["status"])
                    ts = _format_history_timestamp(row["changed_at"])
                    st.markdown(f"• **{label}** — `{ts}`")
