import streamlit as st
from api import update_job_status, delete_job


def _score_class(score: int) -> str:
    if score >= 70:
        return "score-high"
    elif score >= 50:
        return "score-mid"
    return "score-low"


def _badge(text: str, css_class: str) -> str:
    return f'<span class="badge {css_class}">{text}</span>'


def render_job_card(job: dict):
    score = job.get("score", 0)
    ai_status = job.get("ai_status", "")
    user_status = job.get("user_status", "new")
    job_id = job.get("id")
    easy_apply = job.get("easy_apply", False)

    ai_badge = _badge(ai_status, "badge-fit" if ai_status == "fit" else "badge-not_fit")
    us_badge_class = (
        "badge-applied"
        if user_status == "applied"
        else "badge-wont"
        if user_status == "wont_apply"
        else "badge-new"
    )
    us_badge = _badge(user_status, us_badge_class)
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
                'letter-spacing:0.1em;margin-bottom:0.5rem">Actions</div>',
                unsafe_allow_html=True,
            )

            if user_status != "applied":
                if st.button("✅ Applied", key=f"applied_{job_id}", use_container_width=True):
                    update_job_status(job_id, "applied")
                    st.rerun()

            if user_status == "new":
                if st.button("⏭ Won't Apply", key=f"wont_{job_id}", use_container_width=True):
                    update_job_status(job_id, "wont_apply")
                    st.rerun()

            if user_status in ("wont_apply", "applied"):
                if st.button("↩ Reset to New", key=f"reset_{job_id}", use_container_width=True):
                    update_job_status(job_id, "new")
                    st.rerun()

            if st.button("🗑 Delete", key=f"delete_{job_id}", use_container_width=True, type="primary"):
                delete_job(job_id)
                st.session_state.pop("selected_job", None)
                st.rerun()

        if job.get("description"):
            with st.expander("📄 Description"):
                st.write(job["description"])

        if job.get("cover_letter"):
            with st.expander("✉️ Cover Letter"):
                st.text_area(
                    "Cover Letter",
                    job["cover_letter"],
                    height=200,
                    key=f"cl_{job_id}",
                    label_visibility="collapsed",
                )
