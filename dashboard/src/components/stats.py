from html import escape

import streamlit as st

import library
from constants import APPLIED_BUCKET, STRONG_SCORE

# label, key(s), tone — the six numbers worth glancing at, in reading order
TILES = [
    ("Matched", ("fit",), "accent", ""),
    ("New", ("new",), "", ""),
    ("Applied", tuple(APPLIED_BUCKET), "", ""),
    ("Interviewing", ("assessment", "interview"), "warning", ""),
    ("Offers", ("offer",), "good", ""),
    ("Avg score", ("avg_score",), "", ""),
]

# Hover text per tile. Every count is a job's CURRENT status, so a job moved on to
# Interview leaves Applied; the funnel on Analytics counts arrivals instead.
TIPS = {
    "Matched": "Jobs scored {cutoff} or higher, your match cutoff.",
    "New": "Scored jobs with no status set yet.",
    "Applied": "Status is Applied, Email Sent or Referral.",
    "Interviewing": "Status is Assessment or Interview.",
    "Offers": "Status is Offer.",
    "Avg score": "Average score (0-100). Strong matches are {strong}+.",
}


def render_stats(stats: dict | None = None):
    if stats is None:
        stats = library.stats()

    cutoff = library.match_cutoff()
    cols = st.columns(len(TILES), gap="small")
    for col, (label, keys, tone, unit) in zip(cols, TILES):
        value = sum(stats.get(k, 0) or 0 for k in keys)
        tone_class = f" stat-{tone}" if tone else ""
        unit_html = f'<span class="unit">{unit}</span>' if unit else ""
        tip = escape(TIPS[label].format(cutoff=cutoff, strong=STRONG_SCORE))
        with col:
            st.markdown(
                f"""
                <div class="stat-card{tone_class}" title="{tip}">
                  <div class="stat-value">{value}{unit_html}</div>
                  <div class="stat-label">{label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
