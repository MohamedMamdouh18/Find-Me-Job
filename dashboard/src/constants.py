# AI statuses
AI_FIT = "fit"
AI_NOT_FIT = "not_fit"
AI_STATUSES = [AI_FIT, AI_NOT_FIT]

# User statuses
USER_NEW = "new"
USER_APPLIED = "applied"
USER_WONT_APPLY = "wont_apply"
USER_EMAIL_SENT = "email_sent"
USER_STATUSES = [USER_NEW, USER_APPLIED, USER_WONT_APPLY, USER_EMAIL_SENT]

# Badge CSS class mappings
AI_BADGE_CLASS = {
    AI_FIT: "badge-fit",
    AI_NOT_FIT: "badge-not_fit",
}

USER_BADGE_CLASS = {
    USER_NEW: "badge-new",
    USER_APPLIED: "badge-applied",
    USER_WONT_APPLY: "badge-wont",
    USER_EMAIL_SENT: "badge-email_sent",
}

# Chart display labels and colors
AI_STATUS_LABELS = {AI_FIT: "Fit", AI_NOT_FIT: "Not Fit"}
AI_STATUS_COLORS = {AI_FIT: "#4ade80", AI_NOT_FIT: "#f87171"}

USER_STATUS_LABELS = {
    USER_NEW: "New",
    USER_APPLIED: "Applied",
    USER_WONT_APPLY: "Won't Apply",
    USER_EMAIL_SENT: "Email Sent",
}
USER_STATUS_COLORS = {
    USER_NEW: "#60a5fa",
    USER_APPLIED: "#4ade80",
    USER_WONT_APPLY: "#fb923c",
    USER_EMAIL_SENT: "#22d3ee",
}

# Empty stats fallback
EMPTY_STATS = {
    "total": 0,
    AI_FIT: 0,
    AI_NOT_FIT: 0,
    USER_NEW: 0,
    USER_APPLIED: 0,
    USER_WONT_APPLY: 0,
    USER_EMAIL_SENT: 0,
    "avg_score": 0,
}

# Heatmap color scale (dark-to-green, GitHub-style)
HEATMAP_COLORSCALE = [
    [0.0, "#161b22"],
    [0.01, "#0e4429"],
    [0.25, "#006d32"],
    [0.5, "#26a641"],
    [1.0, "#39d353"],
]

# Treemap source palette (循环使用)
SOURCE_COLORS = [
    "#4ade80", "#60a5fa", "#f59e0b", "#f87171", "#a78bfa",
    "#22d3ee", "#fb923c", "#e879f9", "#34d399", "#fbbf24",
]

# Shared chart layout — no hardcoded font_color so Streamlit theme applies
CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(t=40, b=20, l=20, r=20),
    legend=dict(font=dict(size=11)),
)

# Cross-file session state keys
SK_PAGE = "page"
SK_FILTER_KEY = "filter_key"
SK_SELECTED_JOB_INDEX = "selected_job_index"
