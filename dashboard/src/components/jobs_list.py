"""The job list.

Two structural changes over the previous version:

* The detail sits in a column beside the list, and only exists once you pick a
  job: with nothing selected the list gets the full width, and opening one widens
  the page rather than halving the list. The panel is sticky, so it stays level
  with the row it describes instead of scrolling away.
* Status is set from the row. Marking a job Applied used to mean opening the
  panel and finding a dropdown inside it, which is why the funnel, the heatmap
  and half of Analytics had no data to draw: the one event the whole product
  measures was the most expensive thing in it to record.
"""

import re
from html import escape

import streamlit as st

import library
from api import (
    delete_job,
    get_blocked_names,
    get_filtered_jobs,
    get_starred_names,
    toggle_blocked_company,
    toggle_starred_company,
    update_job_status,
)
from components.job_card import render_job_panel
from components.jobs_filters import clear_filters
from components.styles import empty_state
from components.ui import (
    attr_tag,
    human_location,
    keyword_tags,
    list_toolbar,
    md_escape,
    meta_line,
    one_line,
    relative_time,
    score_chip,
    star_mark,
)
from constants import (
    SK_CHECKED_JOB_IDS,
    SK_FILTER_KEY,
    SK_PAGE,
    SK_SELECTED_JOB_ID,
    SK_SELECT_MODE,
    USER_NEW,
    USER_STATUSES,
    USER_STATUS_LABELS,
)

SK_BULK_FEEDBACK = "bulk_action_feedback"
SK_BULK_CONFIRM_DELETE = "bulk_confirm_delete"


@st.cache_data(ttl=60, show_spinner=False)
def _starred_names() -> frozenset:
    return frozenset(get_starred_names())


@st.cache_data(ttl=60, show_spinner=False)
def _blocked_names() -> frozenset:
    return frozenset(get_blocked_names())


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_jobs(filters_tuple, page: int) -> tuple[list[dict], int, int]:
    filters = dict(filters_tuple)
    resp = get_filtered_jobs(
        ai_status=filters["ai_status"],
        user_status=filters["user_status"],
        easy_apply=filters["easy_apply"],
        min_score=filters["min_score"],
        max_score=filters["max_score"],
        search=filters["search"],
        company=filters["company"],
        website=filters["website"],
        location=filters["location"],
        starred_only=filters["starred_only"],
        sort_by=filters["sort_by"],
        sort_order=filters["sort_order"],
        page=page,
        page_size=filters["page_size"],
        include_keywords=True,
    )
    return resp.get("rows", []), resp.get("total", 0), resp.get("pages", 1)


def invalidate_jobs_cache():
    """Everything that reads the jobs table, counts included — a status change
    moves a job between the summary buckets as well as between the rows."""
    _fetch_jobs.clear()  # type: ignore[attr-defined]
    _starred_names.clear()  # type: ignore[attr-defined]
    _blocked_names.clear()  # type: ignore[attr-defined]
    library.refresh()


def _safe_key(job_id: str) -> str:
    """Container keys become CSS class names, so keep them to a safe alphabet."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(job_id)) or "row"


def _clear_checkboxes():
    for key in [k for k in st.session_state if k.startswith("chk_")]:
        del st.session_state[key]
    st.session_state[SK_CHECKED_JOB_IDS] = []
    st.session_state.pop(SK_BULK_CONFIRM_DELETE, None)


def _reset_on_filter_change(filters: dict):
    filter_key = str(sorted(filters.items()))
    if st.session_state.get(SK_FILTER_KEY) != filter_key:
        st.session_state[SK_FILTER_KEY] = filter_key
        st.session_state[SK_PAGE] = 1
        st.session_state[SK_SELECTED_JOB_ID] = None
        _clear_checkboxes()


def _flash(kind: str, msg: str):
    st.session_state[SK_BULK_FEEDBACK] = {"kind": kind, "msg": msg}


def _render_flash():
    """st.rerun() discards messages written just before it, so replay them here."""
    feedback = st.session_state.pop(SK_BULK_FEEDBACK, None)
    if feedback:
        {"success": st.success, "error": st.error, "info": st.info}.get(
            feedback["kind"], st.info
        )(feedback["msg"])


# ── rows ────────────────────────────────────────────────────────────────────


def _set_status(job_id: str, widget_key: str, current: str):
    chosen = st.session_state.get(widget_key)
    if not chosen or chosen == current:
        return
    if update_job_status(job_id, chosen):
        invalidate_jobs_cache()
        _flash("success", f"Moved to {USER_STATUS_LABELS.get(chosen, chosen)}.")


def _render_row(job: dict, starred: frozenset, blocked: frozenset, select_mode: bool,
                selected: bool):
    job_id = str(job.get("id", ""))
    key = _safe_key(job_id)
    company = (job.get("company") or "").strip()
    is_starred = company.lower() in starred
    is_blocked = company.lower() in blocked
    user_status = job.get("user_status", USER_NEW)
    raw_location = one_line(job.get("location", ""))

    # The key drives the row's CSS class, which is how the open row gets its
    # accent rail without wrapping widgets in raw HTML.
    with st.container(border=True, key=f"jobrowsel_{key}" if selected else f"jobrow_{key}"):
        if select_mode:
            check_col, score_col, main_col, action_col = st.columns(
                [0.45, 0.7, 5.4, 2.3], vertical_alignment="center"
            )
            with check_col:
                st.checkbox(
                    "Select", key=f"chk_{key}", label_visibility="collapsed",
                    help=f"Select {one_line(job.get('title', ''))}",
                )
        else:
            score_col, main_col, action_col = st.columns(
                [0.7, 5.85, 2.3], vertical_alignment="center"
            )

        with score_col:
            st.markdown(score_chip(job.get("score", 0)), unsafe_allow_html=True)

        with main_col:
            if st.button(
                md_escape(one_line(job.get("title", "Untitled"))),
                key=f"open_{key}",
                type="tertiary",
                width="stretch",
                help="Open the full posting",
            ):
                st.session_state[SK_SELECTED_JOB_ID] = None if selected else job_id
                st.rerun()

            # A plain anchor rather than a link button: the row already spends a
            # widget on its title and another on its status, and this one only
            # needs to open a URL.
            apply_url = (job.get("applylink") or "").strip()
            link_html = (
                f'<a class="row-link" href="{escape(apply_url, quote=True)}" target="_blank"'
                f' rel="noopener" title="Open the posting">↗</a>'
                if apply_url
                else ""
            )
            marks = "".join(
                m for m in (
                    star_mark(is_starred),
                    attr_tag("⚡ Easy Apply") if job.get("easy_apply") else "",
                    attr_tag("🚫 Blocked") if is_blocked else "",
                ) if m
            )
            st.markdown(
                f'<div class="job-meta"><span class="job-meta-text" '
                f'title="{escape(raw_location, quote=True)}">'
                + meta_line([
                    company,
                    human_location(raw_location),
                    job.get("website", ""),
                    relative_time(job.get("created_at")),
                ])
                + "</span></div>"
                # Second line: the CV skills this posting actually names, and on
                # the right everything that is about the row rather than the job
                # — badges and the link out — on one baseline instead of two.
                f'<div class="job-evidence">{keyword_tags(job.get("keywords") or [])}'
                f'<span class="job-row-marks">{marks}{link_html}</span></div>',
                unsafe_allow_html=True,
            )

        with action_col:
            status_key = f"rowstatus_{key}"
            st.session_state.setdefault(status_key, user_status)
            st.selectbox(
                "Status",
                USER_STATUSES,
                key=status_key,
                label_visibility="collapsed",
                format_func=lambda s: USER_STATUS_LABELS.get(s, s),
                on_change=_set_status,
                args=(job_id, status_key, user_status),
                help="Set where this application stands",
            )


# ── bulk actions ────────────────────────────────────────────────────────────


def _render_bulk_bar(selected_jobs: list[dict], starred: frozenset, blocked: frozenset):
    count = len(selected_jobs)
    companies = {
        (j.get("company") or "").strip().lower(): (j.get("company") or "").strip()
        for j in selected_jobs
        if (j.get("company") or "").strip()
    }

    with st.container(border=True, key="bulk_bar"):
        head, status_col, apply_col = st.columns([1.5, 2.3, 1.2], vertical_alignment="bottom")
        with head:
            st.markdown(
                f'<div class="bulk-count">{count} selected</div>', unsafe_allow_html=True
            )
        with status_col:
            new_status = st.selectbox(
                "Set status",
                USER_STATUSES,
                key="bulk_status",
                format_func=lambda s: USER_STATUS_LABELS.get(s, s),
            )
        with apply_col:
            apply_status = st.button("Apply", key="bulk_apply", width="stretch")

        b1, b2, b3, b4, b5 = st.columns(5)
        star = b1.button("★ Star", key="bulk_star", width="stretch")
        unstar = b2.button("☆ Unstar", key="bulk_unstar", width="stretch")
        block = b3.button("🚫 Block", key="bulk_block", width="stretch",
                          help="Skip these companies on future runs")
        confirming = st.session_state.get(SK_BULK_CONFIRM_DELETE, False)
        delete = b4.button(
            "Confirm delete" if confirming else "🗑 Delete",
            key="bulk_delete",
            width="stretch",
            type="primary" if confirming else "secondary",
        )
        clear = b5.button("Clear", key="bulk_clear", width="stretch")

    if clear:
        _clear_checkboxes()
        st.rerun()

    if apply_status:
        ok = sum(1 for j in selected_jobs if j.get("id") and update_job_status(j["id"], new_status))
        invalidate_jobs_cache()
        _flash("success" if ok else "error", f"Updated {ok}/{count} jobs.")
        st.rerun()

    if star or unstar:
        want_starred = bool(star)
        changed = 0
        for name_lc, name in companies.items():
            if (name_lc in starred) != want_starred:
                toggle_starred_company(name)
                changed += 1
        invalidate_jobs_cache()
        verb = "Starred" if want_starred else "Unstarred"
        _flash("success" if changed else "info",
               f"{verb} {changed} companies." if changed else "Nothing to change.")
        st.rerun()

    if block:
        changed = 0
        for name_lc, name in companies.items():
            if name_lc not in blocked:
                toggle_blocked_company(name)
                changed += 1
        invalidate_jobs_cache()
        _flash("success" if changed else "info",
               f"Blocked {changed} companies." if changed else "All already blocked.")
        st.rerun()

    if delete:
        if not confirming:
            st.session_state[SK_BULK_CONFIRM_DELETE] = True
            st.rerun()
        ok = sum(1 for j in selected_jobs if j.get("id") and delete_job(j["id"]))
        _clear_checkboxes()
        invalidate_jobs_cache()
        _flash("success" if ok else "error", f"Deleted {ok}/{count} jobs.")
        st.rerun()


# ── page ────────────────────────────────────────────────────────────────────


def render_jobs_list(filters: dict, library_total: int):
    st.session_state.setdefault(SK_PAGE, 1)
    st.session_state.setdefault(SK_SELECTED_JOB_ID, None)
    st.session_state.setdefault(SK_SELECT_MODE, False)
    st.session_state.setdefault(SK_CHECKED_JOB_IDS, [])

    _render_flash()
    _reset_on_filter_change(filters)

    starred = _starred_names()
    blocked = _blocked_names()
    jobs, total, total_pages = _fetch_jobs(tuple(sorted(filters.items())), st.session_state[SK_PAGE])

    if not jobs:
        st.session_state[SK_SELECTED_JOB_ID] = None
        _render_empty(filters)
        return

    selected_id = st.session_state.get(SK_SELECTED_JOB_ID)
    if selected_id and selected_id not in {str(j.get("id")) for j in jobs}:
        selected_id = None
        st.session_state[SK_SELECTED_JOB_ID] = None

    if selected_id:
        # A marker the stylesheet keys off to widen the page, so the split never
        # comes out of the list's width.
        st.markdown('<div class="split-open"></div>', unsafe_allow_html=True)
        list_col, detail_col = st.columns([3.1, 2], gap="medium")
    else:
        list_col, detail_col = st.container(), None

    with list_col:
        _render_list(jobs, total, total_pages, filters, library_total, starred, blocked,
                     selected_id)

    if selected_id:
        with detail_col:
            render_job_panel(selected_id, starred, blocked, invalidate_jobs_cache)


def _render_list(jobs, total, total_pages, filters, library_total, starred, blocked, selected_id):
    page = st.session_state[SK_PAGE]
    shown = len(jobs)
    label_col, mode_col = st.columns([3, 1.2], vertical_alignment="center")
    with label_col:
        first = (page - 1) * filters["page_size"] + 1
        span = f"{shown}" if total_pages == 1 else f"{first}–{first + shown - 1}"
        hidden = max(0, library_total - total)
        # Both halves of this sentence come from the same filtered query, and the
        # remainder is stated rather than left to contradict the view chips.
        list_toolbar(
            f"Showing {span} of {total} jobs"
            + (f" · {hidden} hidden by filters" if hidden else "")
        )
    with mode_col:
        select_mode = st.toggle(
            "Select", key=SK_SELECT_MODE, help="Pick several jobs to act on at once"
        )

    bulk_slot = st.container()

    for job in jobs:
        _render_row(job, starred, blocked, select_mode, str(job.get("id")) == selected_id)

    checked_ids = [
        str(j.get("id")) for j in jobs if st.session_state.get(f"chk_{_safe_key(j.get('id'))}")
    ]
    st.session_state[SK_CHECKED_JOB_IDS] = checked_ids
    if select_mode and checked_ids:
        with bulk_slot:
            _render_bulk_bar(
                [j for j in jobs if str(j.get("id")) in set(checked_ids)], starred, blocked
            )
    elif not select_mode:
        st.session_state.pop(SK_BULK_CONFIRM_DELETE, None)

    _render_pagination(total_pages)


def _render_empty(filters: dict):
    """Name the filter that is excluding everything, and offer to drop it."""
    view = st.session_state.get("jobs_view", "All")
    if filters.get("search"):
        empty_state(
            "🔍", "No matching jobs",
            f"Nothing matches “{escape(filters['search'])}”. Try a shorter term, or clear "
            "the search to see the rest of this view.",
        )
    elif view == "New":
        empty_state(
            "✅", "You're all caught up",
            "Every job in this view has been moved out of New. Switch to <b>All</b> to see "
            "everything the pipeline has matched.",
        )
    elif filters.get("min_score", 0) > 0 or filters.get("max_score", 100) < 100:
        empty_state(
            "🎚", "Nothing in that score range",
            f"No job scores between {filters.get('min_score', 0)} and "
            f"{filters.get('max_score', 100)}. Widen the range in <b>Filters</b>.",
        )
    else:
        empty_state(
            "🗂", "No jobs match these filters",
            "Drop a filter to widen the list. If nothing has been scraped yet, open "
            "<b>Settings</b> and press <b>Run now</b>.",
        )
    reset_col, _ = st.columns([1.4, 5])
    with reset_col:
        st.button(
            "Reset filters", key="empty_reset", width="stretch",
            on_click=clear_filters, type="primary",
        )


def _render_pagination(total_pages: int):
    if total_pages <= 1:
        return

    page = st.session_state[SK_PAGE]
    prev_col, label_col, next_col = st.columns([1, 2.4, 1], vertical_alignment="center")
    with prev_col:
        if st.button("← Previous", disabled=page <= 1, width="stretch", key="jobs_prev"):
            st.session_state[SK_PAGE] -= 1
            st.session_state[SK_SELECTED_JOB_ID] = None
            _clear_checkboxes()
            st.rerun()
    with label_col:
        st.markdown(
            f'<div class="pagination-text">Page {page} of {total_pages}</div>',
            unsafe_allow_html=True,
        )
    with next_col:
        if st.button("Next →", disabled=page >= total_pages, width="stretch", key="jobs_next"):
            st.session_state[SK_PAGE] += 1
            st.session_state[SK_SELECTED_JOB_ID] = None
            _clear_checkboxes()
            st.rerun()
