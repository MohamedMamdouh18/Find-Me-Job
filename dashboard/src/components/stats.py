import streamlit as st
from api import get_stats


def render_stats(stats: dict | None = None):
    if stats is None:
        stats = get_stats()

    s1, s2, s3, s4, s5, s6 = st.columns(6)
    for col, label, value in [
        (s1, "Total", stats.get("total", 0)),
        (s2, "Fit", stats.get("fit", 0)),
        (s3, "Not Fit", stats.get("not_fit", 0)),
        (s4, "New", stats.get("new", 0)),
        (s5, "Applied", stats.get("applied", 0)),
        (s6, "Avg Score", stats.get("avg_score", 0)),
    ]:
        with col:
            st.markdown(
                f"""
            <div class="stat-card">
                <div class="stat-value">{value}</div>
                <div class="stat-label">{label}</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

    st.write("")
