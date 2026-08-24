"""Search, views and filters for the Jobs page.

The rule this file exists to enforce: what the screen says is showing, and what
is actually showing, are the same thing. The view chips used to be labelled with
whole-library counts while the list below them was silently filtered to a
minimum score of 60 and an AI verdict of Matched, so "All 10" sat directly above
"Showing 6 of 6". Defaults are neutral now, and anything narrowing the list is
named in a chip you can click off.
"""

import streamlit as st

from api import get_filter_options
from components.ui import list_toolbar
from constants import (
    AI_STATUSES,
    MATCH_CUTOFF,
    STRONG_SCORE,
    USER_STATUSES,
    USER_STATUS_LABELS,
)

VIEW_ALL = "All"
VIEW_MATCHED = "Matched"
VIEW_STRONG = "Strong"
VIEW_NEW = "New"
VIEW_EASY = "Easy Apply"
VIEW_STARRED = "Starred"
VIEWS = [VIEW_ALL, VIEW_MATCHED, VIEW_STRONG, VIEW_NEW, VIEW_EASY, VIEW_STARRED]

VIEW_ICONS = {VIEW_EASY: "⚡ ", VIEW_STARRED: "★ "}
# Which count belongs on which chip. Starred has no cheap library-wide count, so
# it ships without one rather than with a guess.
VIEW_COUNT_KEYS = {
    VIEW_ALL: "total",
    VIEW_MATCHED: "matched",
    VIEW_STRONG: "strong",
    VIEW_NEW: "new",
    VIEW_EASY: "easy_apply",
}
VIEW_HELP = {
    VIEW_ALL: "Every scored job, nothing hidden",
    VIEW_MATCHED: f"The AI scored these {MATCH_CUTOFF} or above",
    VIEW_STRONG: f"Scored {STRONG_SCORE} or above",
    VIEW_NEW: "Scored, not yet moved out of New",
    VIEW_EASY: "LinkedIn Easy Apply postings",
    VIEW_STARRED: "Jobs at companies you starred",
}

# The score floor and verdict a view owns, so a view can never disagree with the
# controls in the popover.
VIEW_SCORE_FLOOR = {VIEW_MATCHED: MATCH_CUTOFF, VIEW_STRONG: STRONG_SCORE}

SORT_OPTIONS = {
    "score_desc": ("Match score", "score", "desc"),
    "score_asc": ("Lowest score", "score", "asc"),
    "created_desc": ("Newest first", "created_at", "desc"),
    "updated_desc": ("Recently updated", "updated_at", "desc"),
    "company_asc": ("Company A–Z", "company", "asc"),
    "title_asc": ("Title A–Z", "title", "asc"),
}

SK_RANGE = "jobs_score_range"

# Neutral by default. A first-run user must never be shown a filtered list under
# a heading that says "All".
_ADVANCED_DEFAULTS = {
    SK_RANGE: (0, 100),
    "jobs_ai_status": "all",
    "jobs_user_status": "all",
    "jobs_easy_only": False,
    "jobs_company": "all",
    "jobs_website": "all",
    "jobs_location": "all",
}
_DEFAULTS = {
    "jobs_view": VIEW_ALL,
    "jobs_search": "",
    "jobs_sort": "score_desc",
    "jobs_page_size": 20,
    **_ADVANCED_DEFAULTS,
}


@st.cache_data(ttl=300, show_spinner=False)
def _cached_filter_options() -> dict:
    return get_filter_options()


def _none_if_all(value: str) -> str | None:
    return None if value == "all" else value


def _init_defaults():
    for key, value in _DEFAULTS.items():
        st.session_state.setdefault(key, value)


def _coerce_view():
    """Clicking the active chip deselects it; an empty view row reads as broken."""
    if not st.session_state.get("jobs_view"):
        st.session_state["jobs_view"] = VIEW_ALL


def clear_filters():
    for key, value in _ADVANCED_DEFAULTS.items():
        st.session_state[key] = value


def _clear_all():
    for key, value in _DEFAULTS.items():
        st.session_state[key] = value


def apply_preset(view: str, score_range: tuple[int, int] | None = None):
    """Used by the Analytics attention list, so a nudge lands on the exact slice
    it named rather than on a page the user then has to filter themselves."""
    clear_filters()
    st.session_state["jobs_view"] = view
    st.session_state["jobs_search"] = ""
    if score_range:
        st.session_state[SK_RANGE] = score_range
        st.session_state["jobs_sort"] = "score_desc" if score_range[0] else "score_asc"


# ── active filter chips ─────────────────────────────────────────────────────


def _active_chips() -> list[tuple[str, str, object]]:
    """(session key, label, value to reset to) for everything narrowing the list."""
    chips: list[tuple[str, str, object]] = []
    low, high = st.session_state.get(SK_RANGE, (0, 100))
    if (low, high) != (0, 100):
        if high < 100 and low == 0:
            label = f"score under {high + 1}"
        elif low > 0 and high == 100:
            label = f"score {low}+"
        else:
            label = f"score {low}–{high}"
        chips.append((SK_RANGE, label, (0, 100)))

    verdict = st.session_state.get("jobs_ai_status", "all")
    if verdict != "all":
        chips.append((
            "jobs_ai_status",
            f"verdict: {'Matched' if verdict == 'fit' else 'Not a match'}",
            "all",
        ))

    status = st.session_state.get("jobs_user_status", "all")
    if status != "all":
        chips.append((
            "jobs_user_status", f"status: {USER_STATUS_LABELS.get(status, status)}", "all"
        ))

    if st.session_state.get("jobs_easy_only"):
        chips.append(("jobs_easy_only", "Easy Apply only", False))

    for key, prefix in (
        ("jobs_company", "company"),
        ("jobs_website", "source"),
        ("jobs_location", "location"),
    ):
        value = st.session_state.get(key, "all")
        if value != "all":
            chips.append((key, f"{prefix}: {value}", "all"))
    return chips


def _set(key: str, value):
    st.session_state[key] = value


def _render_chips(chips: list, view: str, search: str):
    """One click removes one filter. A filter you cannot see is a filter you
    cannot undo, which is how the old default score floor stayed invisible.

    The resets run as on_click callbacks, not inline: these chips are drawn after
    the controls they reset, and Streamlit refuses a write to a widget's key once
    that widget exists in the current run.
    """
    if not chips and view == VIEW_ALL and not search:
        return

    with st.container(horizontal=True, key="filter_chips"):
        st.markdown('<span class="chip-lead">Filters</span>', unsafe_allow_html=True)
        if view != VIEW_ALL:
            st.button(f"{view}  ✕", key="chip_view", type="tertiary",
                      on_click=_set, args=("jobs_view", VIEW_ALL))
        if search:
            st.button(f"“{search}”  ✕", key="chip_search", type="tertiary",
                      on_click=_set, args=("jobs_search", ""))
        for key, label, reset in chips:
            st.button(f"{label}  ✕", key=f"chip_{key}", type="tertiary",
                      on_click=_set, args=(key, reset))
        st.button("Clear all", key="chip_clear_all", type="tertiary", on_click=_clear_all)


# ── page ────────────────────────────────────────────────────────────────────


def _view_label(view: str, counts: dict) -> str:
    key = VIEW_COUNT_KEYS.get(view)
    count = counts.get(key) if key else None
    icon = VIEW_ICONS.get(view, "")
    return f"{icon}{view}  {count}" if count is not None else f"{icon}{view}"


def render_jobs_filters(counts: dict) -> dict:
    _init_defaults()
    options = _cached_filter_options()

    search_col, sort_col = st.columns([5.2, 1.9], vertical_alignment="center")
    with search_col:
        search = st.text_input(
            "Search",
            key="jobs_search",
            label_visibility="collapsed",
            placeholder="Search jobs, companies or locations…",
        )
    with sort_col:
        sort_key = st.selectbox(
            "Sort",
            list(SORT_OPTIONS),
            key="jobs_sort",
            label_visibility="collapsed",
            format_func=lambda k: f"Sort: {SORT_OPTIONS[k][0]}",
        )

    view_col, filter_col = st.columns([5.2, 1.9], vertical_alignment="center")
    with view_col:
        st.segmented_control(
            "View",
            VIEWS,
            key="jobs_view",
            label_visibility="collapsed",
            format_func=lambda v: _view_label(v, counts),
            on_change=_coerce_view,
            help=VIEW_HELP.get(st.session_state.get("jobs_view") or VIEW_ALL),
        )
    view = st.session_state.get("jobs_view") or VIEW_ALL

    chips = _active_chips()
    with filter_col:
        with st.popover(
            f"Filters · {len(chips)}" if chips else "Filters",
            icon=":material/tune:",
            width=430,
        ):
            advanced = _render_advanced(options, view)

    _render_chips(chips, view, search.strip())

    low, high = advanced["score_range"]
    low = max(low, VIEW_SCORE_FLOOR.get(view, 0))

    return {
        "ai_status": _none_if_all(advanced["ai_status"]),
        "user_status": "new" if view == VIEW_NEW else _none_if_all(advanced["user_status"]),
        "easy_apply": True if (view == VIEW_EASY or advanced["easy_only"]) else None,
        "min_score": low,
        "max_score": high,
        "search": search.strip() or None,
        "company": _none_if_all(advanced["company"]),
        "website": _none_if_all(advanced["website"]),
        "location": _none_if_all(advanced["location"]),
        "starred_only": view == VIEW_STARRED,
        "sort_by": SORT_OPTIONS[sort_key][1],
        "sort_order": SORT_OPTIONS[sort_key][2],
        "page_size": st.session_state.get("jobs_page_size", 20),
    }


def _render_advanced(options: dict, view: str) -> dict:
    list_toolbar("Refine")

    floor = VIEW_SCORE_FLOOR.get(view)
    score_range = st.slider(
        "Match score",
        0,
        100,
        key=SK_RANGE,
        help=(
            f"The {view} view already sets a floor of {floor}."
            if floor
            else f"Matched jobs are the ones scored {MATCH_CUTOFF} or above."
        ),
    )

    stage_owned = view == VIEW_NEW
    c1, c2 = st.columns(2)
    with c1:
        user_status = st.selectbox(
            "Application status",
            ["all"] + USER_STATUSES,
            key="jobs_user_status",
            disabled=stage_owned,
            format_func=lambda x: "Any status" if x == "all" else USER_STATUS_LABELS.get(x, x.title()),
            help="The New view sets this to New." if stage_owned else None,
        )
    with c2:
        ai_status = st.selectbox(
            "AI verdict",
            ["all"] + AI_STATUSES,
            key="jobs_ai_status",
            format_func=lambda x: {"all": "Any verdict", "fit": "Matched", "not_fit": "Not a match"}[x],
            help=f"The verdict is written at score {MATCH_CUTOFF}, so it moves with the slider.",
        )

    c3, c4 = st.columns(2)
    with c3:
        website = st.selectbox(
            "Source", ["all"] + options.get("websites", []), key="jobs_website",
            format_func=lambda x: "Any source" if x == "all" else x,
        )
    with c4:
        location = st.selectbox(
            "Location", ["all"] + options.get("locations", []), key="jobs_location",
            format_func=lambda x: "Anywhere" if x == "all" else x,
        )

    c5, c6 = st.columns(2)
    with c5:
        company = st.selectbox(
            "Company", ["all"] + options.get("companies", []), key="jobs_company",
            format_func=lambda x: "Any company" if x == "all" else x,
        )
    with c6:
        st.selectbox("Jobs per page", [10, 20, 50, 100], key="jobs_page_size")

    easy_only = st.checkbox(
        "Easy Apply only", key="jobs_easy_only", disabled=view == VIEW_EASY,
        help="The Easy Apply view already does this." if view == VIEW_EASY else None,
    )

    st.button("Reset filters", key="jobs_clear_filters", on_click=clear_filters, width="stretch")

    return {
        "score_range": score_range,
        "user_status": user_status,
        "ai_status": ai_status,
        "easy_only": easy_only,
        "website": website,
        "location": location,
        "company": company,
    }
