# AI statuses
AI_FIT = "fit"
AI_NOT_FIT = "not_fit"
AI_STATUSES = [AI_FIT, AI_NOT_FIT]

# User statuses
USER_NEW = "new"
USER_APPLIED = "applied"
USER_EMAIL_SENT = "email_sent"
USER_REFERRAL = "referral"
USER_ASSESSMENT = "assessment"
USER_INTERVIEW = "interview"
USER_OFFER = "offer"
USER_REJECTED = "rejected"
USER_WONT_APPLY = "wont_apply"

USER_STATUSES = [
    USER_NEW,
    USER_APPLIED,
    USER_EMAIL_SENT,
    USER_REFERRAL,
    USER_ASSESSMENT,
    USER_INTERVIEW,
    USER_OFFER,
    USER_REJECTED,
    USER_WONT_APPLY,
]

# Statuses that count as "applied" in analytics (multiple application methods)
APPLIED_BUCKET = {USER_APPLIED, USER_EMAIL_SENT, USER_REFERRAL}

# Badge CSS class mappings
AI_BADGE_CLASS = {
    AI_FIT: "badge-fit",
    AI_NOT_FIT: "badge-not_fit",
}

USER_BADGE_CLASS = {
    USER_NEW: "badge-new",
    USER_APPLIED: "badge-applied",
    USER_EMAIL_SENT: "badge-email_sent",
    USER_REFERRAL: "badge-referral",
    USER_ASSESSMENT: "badge-assessment",
    USER_INTERVIEW: "badge-interview",
    USER_OFFER: "badge-offer",
    USER_REJECTED: "badge-rejected",
    USER_WONT_APPLY: "badge-wont",
}

# Chart display labels and colors — sourced from the validated palette in theme.py
from theme import (  # noqa: E402
    AQUA, BLUE, CRITICAL, GOOD, NEUTRAL, ORANGE, SEQ, VIOLET, WARNING,
)

AI_STATUS_LABELS = {AI_FIT: "Fit", AI_NOT_FIT: "Not Fit"}
# Fit is the subject; "not fit" recedes to neutral instead of shouting red.
AI_STATUS_COLORS = {AI_FIT: BLUE, AI_NOT_FIT: NEUTRAL}

USER_STATUS_LABELS = {
    USER_NEW: "New",
    USER_APPLIED: "Applied",
    USER_EMAIL_SENT: "Email Sent",
    USER_REFERRAL: "Referral",
    USER_ASSESSMENT: "Assessment",
    USER_INTERVIEW: "Interview",
    USER_OFFER: "Offer",
    USER_REJECTED: "Rejected",
    USER_WONT_APPLY: "Won't Apply",
}

# The pipeline is ordered, so the live stages walk one hue from light to dark;
# terminal outcomes step outside that ramp so they read as endings, not stages.
USER_STATUS_COLORS = {
    USER_NEW: SEQ[250],
    USER_APPLIED: SEQ[350],
    USER_EMAIL_SENT: SEQ[400],
    USER_REFERRAL: SEQ[450],
    USER_ASSESSMENT: SEQ[500],
    USER_INTERVIEW: SEQ[600],
    USER_OFFER: GOOD,
    USER_REJECTED: CRITICAL,
    USER_WONT_APPLY: NEUTRAL,
}

# Empty stats fallback
EMPTY_STATS = {
    "total": 0,
    AI_FIT: 0,
    AI_NOT_FIT: 0,
    **{s: 0 for s in USER_STATUSES},
    "avg_score": 0,
    "easy_apply": 0,
}

# Heatmap: single hue, light -> dark. The old scale started at near-black and
# painted a solid dark grid onto a light page.
from theme import SEQUENTIAL_SCALE as HEATMAP_COLORSCALE  # noqa: E402,F401

# Sources are identities, so fixed categorical slots in order — never cycled.
SOURCE_COLORS = [BLUE, ORANGE, AQUA, WARNING, VIOLET]

from theme import CHART_LAYOUT  # noqa: E402,F401

# Score thresholds live with the colours that encode them, so a band and its
# label can never drift apart. Re-exported here because every page imports
# constants and almost none import theme directly.
from theme import (  # noqa: E402,F401
    BAND_LABELS, MATCH_CUTOFF, STRONG_SCORE, score_band,
)

# Cross-file session state keys
SK_PAGE = "page"
SK_FILTER_KEY = "filter_key"
SK_SELECTED_JOB_ID = "selected_job_id"
SK_SELECT_MODE = "jobs_select_mode"
SK_CHECKED_JOB_IDS = "checked_job_ids"
