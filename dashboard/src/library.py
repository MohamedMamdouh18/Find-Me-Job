"""The one place counts are computed.

Analytics, Jobs, Companies, Settings and the sidebar all read this module. If a
number appears on two screens it comes from one field of one of these objects,
so the pages can no longer disagree about how many jobs there are.

The vocabulary is fixed here too, because most of the old disagreement was two
screens using the same word for different sets:

    Scored / in DB   a row exists in filtered_jobs and carries a score
    Queued           scraped, waiting for the scorer — not in filtered_jobs yet
    Matched          score >= MATCH_CUTOFF, which is exactly ai_status == "fit"
    Strong match     score >= STRONG_SCORE
    New              scored, still at user_status "new"
"""

from datetime import datetime

import streamlit as st

from api import (
    get_blocked_companies,
    get_current_run,
    get_daily_applied,
    get_funnel,
    get_pending_count,
    get_runs,
    get_score_distribution,
    get_starred_companies,
    get_stats,
    get_stats_by_source,
    get_top_companies,
)
from theme import MATCH_CUTOFF, STRONG_SCORE

STATS_TTL = 20
HEALTH_TTL = 15

STARRED = "starred"
BLOCKED = "blocked"


@st.cache_data(ttl=STATS_TTL, show_spinner=False)
def stats() -> dict:
    """Every job count in the app. One request, one shape, one meaning per key."""
    raw = get_stats()
    bins = get_score_distribution()
    strong = sum(b["count"] for b in bins if b.get("start", 0) >= STRONG_SCORE)
    below = sum(b["count"] for b in bins if b.get("start", 0) + 9 < MATCH_CUTOFF)
    return {
        **raw,
        # Stamped inside the cached call, so it is the age of these numbers and
        # not the age of the page that drew them.
        "fetched_at": datetime.now().isoformat(),
        "bins": bins,
        "strong": strong,
        "below_cutoff": below,
        "queue": get_pending_count(),
        "matched": raw.get("fit", 0) or 0,
    }


@st.cache_data(ttl=STATS_TTL, show_spinner=False)
def funnel() -> dict:
    return get_funnel()


@st.cache_data(ttl=HEALTH_TTL, show_spinner=False)
def health() -> dict:
    runs = get_runs(1)
    return {
        "current_run": get_current_run(),
        "last_run": runs[0] if runs else None,
        "fetched_at": datetime.now().isoformat(),
    }


@st.cache_data(ttl=STATS_TTL, show_spinner=False)
def sources() -> list[dict]:
    return get_stats_by_source()


@st.cache_data(ttl=STATS_TTL, show_spinner=False)
def daily_applied(days: int) -> list[dict]:
    return get_daily_applied(days)


@st.cache_data(ttl=STATS_TTL, show_spinner=False)
def companies() -> list[dict]:
    """Both lists in one payload so a single search and sort covers the page."""
    return [{**c, "kind": STARRED} for c in get_starred_companies()] + [
        {**c, "kind": BLOCKED} for c in get_blocked_companies()
    ]


@st.cache_data(ttl=STATS_TTL, show_spinner=False)
def company_stats() -> dict:
    """company name (lowercased) -> jobs seen, best score, last seen."""
    return {c["company"].strip().lower(): c for c in get_top_companies(limit=100)}


def refresh():
    for fn in (stats, funnel, health, companies, company_stats, sources, daily_applied):
        fn.clear()  # type: ignore[attr-defined]


# ── needs attention ─────────────────────────────────────────────────────────

# (page, view) the caller can jump to; the caller owns navigation, this owns
# the conditions, so the sidebar badge and the Analytics list can never differ.
def attention(counts: dict, hlth: dict) -> list[dict]:
    """Conditions that are true right now and have somewhere to go.

    Only real state — no thresholds invented to manufacture an item. An empty
    list means nothing needs doing, and the section hides itself.
    """
    items: list[dict] = []
    queue = counts.get("queue", 0)
    current_run = hlth.get("current_run")
    last_run = hlth.get("last_run")

    if current_run:
        items.append({
            "tone": "ok",
            "text": f"Pipeline is running: {current_run.get('stage', 'in progress')}.",
            "action": "View live", "page": "Settings",
        })
    elif last_run and last_run.get("status") == "failed":
        items.append({
            "tone": "fail",
            "text": f"Last run failed: {last_run.get('error', 'unknown error')}.",
            "action": "Check Run", "page": "Settings",
        })
    elif queue:
        items.append({
            "tone": "idle",
            "text": f"{queue:,} jobs are queued for scoring.",
            "action": "Open Settings", "page": "Settings",
        })

    strong_new = min(counts.get("strong", 0), counts.get("new", 0))
    if strong_new:
        items.append({
            "tone": "ok",
            "text": f"{strong_new} strong matches you have not opened yet.",
            "action": "Show me", "page": "Jobs", "view": "Strong",
        })

    below = counts.get("below_cutoff", 0)
    if below:
        items.append({
            "tone": "idle",
            "text": f"{below} jobs scored below your cutoff of {MATCH_CUTOFF}.",
            "action": "Review", "page": "Jobs", "view": "Below cutoff",
        })

    if counts.get("total", 0) and not counts.get("applied_ever", 0):
        items.append({
            "tone": "idle",
            "text": "No applications yet — mark one Applied to start your pipeline.",
            "action": "Go to Jobs", "page": "Jobs", "view": "Matched",
        })
    return items
