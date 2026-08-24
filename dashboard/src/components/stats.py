import streamlit as st

import library
from constants import APPLIED_BUCKET

# label, key(s), tone — the six numbers worth glancing at, in reading order
TILES = [
    ("Matched", ("fit",), "accent", ""),
    ("New", ("new",), "", ""),
    ("Applied", tuple(APPLIED_BUCKET), "", ""),
    ("Interviewing", ("assessment", "interview"), "warning", ""),
    ("Offers", ("offer",), "good", ""),
    ("Avg score", ("avg_score",), "", ""),
]


def render_stats(stats: dict | None = None):
    if stats is None:
        stats = library.stats()

    cols = st.columns(len(TILES), gap="small")
    for col, (label, keys, tone, unit) in zip(cols, TILES):
        value = sum(stats.get(k, 0) or 0 for k in keys)
        tone_class = f" stat-{tone}" if tone else ""
        unit_html = f'<span class="unit">{unit}</span>' if unit else ""
        with col:
            st.markdown(
                f"""
                <div class="stat-card{tone_class}">
                  <div class="stat-value">{value}{unit_html}</div>
                  <div class="stat-label">{label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
