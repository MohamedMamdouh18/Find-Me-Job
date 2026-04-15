import streamlit as st


def inject_styles():
    st.markdown(
        """
<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', sans-serif;
    }
    /* .main inherits from Streamlit theme */
    .block-container { padding: 2rem 2rem 2rem 2rem; max-width: 1800px; }

    .stat-card {
        background: var(--secondary-background-color, #1a1a1a);
        border: 1px solid var(--secondary-background-color, #2a2a2a);
        border-radius: 8px;
        padding: 1.2rem 1.5rem;
        text-align: center;
    }
    .stat-value {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 2rem;
        font-weight: 600;
        color: var(--text-color, #e8e8e8);
        line-height: 1;
    }
    .stat-label {
        font-size: 0.75rem;
        color: var(--text-color, #666);
        opacity: 0.6;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-top: 0.4rem;
    }

    .section-title {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.7rem;
        color: var(--text-color, #444);
        opacity: 0.5;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--secondary-background-color, #1f1f1f);
    }

    .score-high { color: #4ade80; font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
    .score-mid  { color: #facc15; font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
    .score-low  { color: #f87171; font-family: 'IBM Plex Mono', monospace; font-weight: 600; }

    .badge {
        display: inline-block;
        font-size: 0.7rem;
        font-family: 'IBM Plex Mono', monospace;
        padding: 0.15rem 0.5rem;
        border-radius: 4px;
        margin-right: 0.3rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .badge-fit        { background: #14532d; color: #4ade80; }
    .badge-not_fit    { background: #450a0a; color: #f87171; }
    .badge-new        { background: #1e3a5f; color: #60a5fa; }
    .badge-applied    { background: #14532d; color: #4ade80; }
    .badge-email_sent { background: #0c3347; color: #22d3ee; }
    .badge-referral   { background: #2e1065; color: #a78bfa; }
    .badge-assessment { background: #422006; color: #facc15; }
    .badge-interview  { background: #431407; color: #fb923c; }
    .badge-offer      { background: #064e3b; color: #34d399; }
    .badge-rejected   { background: #450a0a; color: #f87171; }
    .badge-wont       { background: #1f2937; color: #94a3b8; }
    .badge-easy       { background: #1a1a2e; color: #a78bfa; }

    div[data-testid="stButton"] button {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.75rem;
        border-radius: 4px;
    }

    div[data-testid="stExpander"] {
        background: var(--secondary-background-color);
        border: 1px solid var(--secondary-background-color);
        border-radius: 6px;
    }

    .pagination-text {
        text-align: center;
        opacity: 0.5;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.8rem;
        padding-top: 0.5rem;
    }

    /* Data table */
    [data-testid="stDataFrame"] {
        border-radius: 6px;
    }
</style>
""",
        unsafe_allow_html=True,
    )
