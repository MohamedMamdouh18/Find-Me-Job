"""The job detail, as a dialog.

It leads with the evidence rather than the number. The score used to be the only
thing the app said about a match, which asks the reader to trust a figure with
nothing behind it; the block at the top now names which of the skills extracted
from the CV this posting actually asks for, and says plainly that this is a
keyword overlap and not the model's own reasoning — the scoring node returns
`{score, coverLetter}` and no rationale to show.
"""

import re
from html import escape

import streamlit as st

from api import (
    delete_job,
    get_filtered_job,
    get_job_history,
    get_job_match,
    toggle_blocked_company,
    toggle_starred_company,
    update_job_status,
)
from pdf import build_pdf
from components.ui import (
    attr_tag,
    format_date,
    human_location,
    one_line,
    relative_time,
    score_chip,
    state_badge,
)
from constants import (
    AI_BADGE_CLASS,
    AI_NOT_FIT,
    BAND_LABELS,
    SK_SELECTED_JOB_ID,
    USER_BADGE_CLASS,
    USER_NEW,
    USER_STATUSES,
    USER_STATUS_LABELS,
    score_band,
)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_history(job_id: str) -> list[dict]:
    return get_job_history(job_id)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_detail(job_id: str) -> dict | None:
    return get_filtered_job(job_id)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_match(job_id: str) -> dict:
    return get_job_match(job_id)


@st.cache_data(show_spinner=False, max_entries=32)
def _cached_pdf(text: str, title: str, company: str) -> bytes:
    """Rendering the PDF is not free and the dialog re-renders on every rerun."""
    return build_pdf(text, title, company)


def _clear_detail_caches():
    _cached_history.clear()  # type: ignore[attr-defined]
    _cached_detail.clear()  # type: ignore[attr-defined]
    _cached_match.clear()  # type: ignore[attr-defined]


# ── description ─────────────────────────────────────────────────────────────

_BULLET = re.compile(r"(?:^|\s)\*\s+")


def format_description(text: str, highlight: list[str] | None = None) -> str:
    """Scraped postings arrive as one unbroken line with `*` bullets run into the
    prose. Restore the bullets and highlight the CV skills; do not try to infer
    section headings, which would mean guessing where the writer's breaks were."""
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""

    parts = [p.strip() for p in _BULLET.split(flat)]
    lead, bullets = parts[0], [p for p in parts[1:] if p]

    html = f"<p>{_mark(lead, highlight)}</p>" if lead else ""
    if bullets:
        html += "<ul>" + "".join(f"<li>{_mark(b, highlight)}</li>" for b in bullets) + "</ul>"
    return html


def _mark(text: str, words: list[str] | None) -> str:
    """One alternation pass, so a highlight can never land inside a tag emitted
    by an earlier one."""
    safe = escape(text)
    terms = [re.escape(escape(w)) for w in (words or []) if w]
    if not terms:
        return safe
    pattern = re.compile(r"(?<![\w])(" + "|".join(sorted(terms, key=len, reverse=True)) + r")(?![\w])",
                         re.IGNORECASE)
    return pattern.sub(r'<mark class="kw-hit">\1</mark>', safe)


# ── dialog ──────────────────────────────────────────────────────────────────


def _apply_status(job_id: str, widget_key: str, current: str, on_change):
    """Status commits the moment it is picked — a separate Update button was a dead click."""
    chosen = st.session_state.get(widget_key)
    if not chosen or chosen == current:
        return
    if update_job_status(job_id, chosen):
        _clear_detail_caches()
        if on_change:
            on_change()
        st.session_state["job_toast"] = f"Moved to {USER_STATUS_LABELS.get(chosen, chosen)}"


def _close():
    st.session_state[SK_SELECTED_JOB_ID] = None


def render_job_panel(
    job_id: str,
    starred_names: frozenset = frozenset(),
    blocked_names: frozenset = frozenset(),
    on_change=None,
):
    """The detail as a column beside the list, not a modal over it: a dialog dims
    the list you are comparing against, and closing it is the only way back."""
    job = _cached_detail(job_id)
    with st.container(border=True, key="job_detail"):
        if not job or not job.get("id"):
            st.error("This job is no longer in the database.")
            st.button("Close", key="detail_gone_close", on_click=_close, width="stretch")
            return
        st.button("✕", key=f"close_{job_id}", help="Close", on_click=_close)
        render_job_detail(job, starred_names, blocked_names, on_change)


def render_job_detail(job: dict, starred_names, blocked_names, on_change):
    job_id = str(job.get("id", ""))
    title = one_line(job.get("title", "N/A"))
    company = (job.get("company") or "").strip()
    is_starred = company.lower() in starred_names
    is_blocked = company.lower() in blocked_names
    user_status = job.get("user_status", USER_NEW)
    ai_status = job.get("ai_status", "")
    score = job.get("score", 0)
    raw_location = one_line(job.get("location", ""))

    facts = [
        company,
        human_location(raw_location),
        str(job.get("website", "") or ""),
        f"scored {relative_time(job.get('created_at'))}" if job.get("created_at") else "",
    ]
    st.markdown(
        f'<div class="detail-title">{escape(title)}</div>'
        '<div class="detail-facts-line">'
        + '<span class="meta-sep">·</span>'.join(escape(f) for f in facts if f)
        + "</div>",
        unsafe_allow_html=True,
    )

    marks = [
        attr_tag("⚡ Easy Apply") if job.get("easy_apply") else "",
        state_badge(
            {"fit": "Matched", "not_fit": "Not a match"}.get(ai_status, ai_status or "—"),
            AI_BADGE_CLASS.get(ai_status, AI_BADGE_CLASS[AI_NOT_FIT]),
        ),
        state_badge(
            USER_STATUS_LABELS.get(user_status, user_status),
            USER_BADGE_CLASS.get(user_status, USER_BADGE_CLASS[USER_NEW]),
        ),
        '<span class="star-mark">★ Starred</span>' if is_starred else "",
        attr_tag("🚫 Blocked") if is_blocked else "",
    ]
    st.markdown(
        f'<div class="detail-headline">{score_chip(score)}'
        f'<span class="detail-band">{escape(BAND_LABELS[score_band(score)])}</span>'
        f'<span class="detail-marks">{"".join(m for m in marks if m)}</span></div>',
        unsafe_allow_html=True,
    )

    evidence = _cached_match(job_id)
    matched = evidence.get("matched") or []
    _render_evidence(score, matched, evidence.get("skills_known", 0))

    _render_actions(job, job_id, company, is_starred, is_blocked, on_change)

    st.markdown('<div class="detail-label">Application status</div>', unsafe_allow_html=True)
    status_key = f"dlgstatus_{job_id}"
    st.session_state.setdefault(status_key, user_status)
    status_col, _ = st.columns([3, 2])
    with status_col:
        st.selectbox(
            "Application status",
            USER_STATUSES,
            key=status_key,
            label_visibility="collapsed",
            format_func=lambda s: USER_STATUS_LABELS.get(s, s),
            on_change=_apply_status,
            args=(job_id, status_key, user_status, on_change),
        )

    description = job.get("description")
    if description:
        st.markdown('<div class="detail-label">Job description</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="posting">{format_description(description, matched)}</div>',
            unsafe_allow_html=True,
        )

    if job.get("application_document"):
        with st.expander("✉️ Application document"):
            st.text_area(
                "Application document",
                job["application_document"],
                height=200,
                key=f"cl_{job_id}",
                label_visibility="collapsed",
            )
            st.download_button(
                "Download as PDF",
                data=_cached_pdf(job["application_document"], title, company),
                file_name=f"{title} - {company}.pdf".replace("/", "-"),
                mime="application/pdf",
                key=f"pdf_{job_id}",
                width="stretch",
                icon=":material/download:",
            )

    _render_timeline(job, job_id)
    _render_delete(job_id, on_change)


def _render_evidence(score, matched: list[str], skills_known: int):
    """Only the half that says something about the job.

    The inverse — CV skills this posting happens not to mention — was eight tags
    of noise per row: "MySQL not found" in an AI residency posting is not a gap
    in the candidate, it is a fact about a different job.
    """
    st.markdown(
        f'<div class="detail-label">Why this scored {int(score or 0)}</div>',
        unsafe_allow_html=True,
    )
    if not skills_known:
        st.markdown(
            '<div class="mono-note">No CV keywords have been extracted yet, so there is '
            "nothing to compare this posting against. They are extracted on the first run "
            "after a CV change.</div>",
            unsafe_allow_html=True,
        )
        return

    if matched:
        st.markdown(
            '<div class="evidence"><div class="ev-row"><span class="ev-label">In your CV</span>'
            + "".join(f'<span class="tag tag-strong">{escape(m)}</span>' for m in matched)
            + "</div></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="evidence"><div class="ev-row"><span class="ev-label">In your CV</span>'
            '<span class="ev-none">none of your extracted skills appear in this posting'
            "</span></div></div>",
            unsafe_allow_html=True,
        )
    hits = len(matched)
    st.caption(
        f"{hits} of your {skills_known} extracted CV skills "
        f"{'appears' if hits == 1 else 'appear'} in this posting. That is a keyword overlap, "
        "not the scorer's reasoning — the scoring step records a score and a cover letter and "
        "no rationale, so this is evidence for the number rather than an explanation of it."
    )


def _render_actions(job, job_id, company, is_starred, is_blocked, on_change):
    apply_url = job.get("applylink") or ""
    open_col, star_col, block_col = st.columns([2.4, 1.5, 1.5])
    with open_col:
        if apply_url:
            st.link_button(
                "Open posting",
                apply_url,
                width="stretch",
                type="primary",
                icon=":material/open_in_new:",
            )
        else:
            st.button("No link on this posting", disabled=True, width="stretch", key=f"nolink_{job_id}")
    with star_col:
        if st.button(
            "★ Unstar" if is_starred else "☆ Star",
            key=f"star_{job_id}",
            width="stretch",
            help="Starred companies get a ★ in the list and their own view. Starring does "
                 "not change how a job is scored.",
        ):
            toggle_starred_company(company)
            if on_change:
                on_change()
            st.rerun()
    with block_col:
        if st.button(
            "♻ Unblock" if is_blocked else "🚫 Block",
            key=f"block_{job_id}",
            width="stretch",
            help="Stop blocking this company"
            if is_blocked
            else "New postings from this company are dropped before scoring. Jobs already "
                 "in your list stay.",
        ):
            toggle_blocked_company(company)
            if on_change:
                on_change()
            st.rerun()


def _render_timeline(job: dict, job_id: str):
    st.markdown('<div class="detail-label">Timeline</div>', unsafe_allow_html=True)
    rows = [("Scored", job.get("created_at"))]
    for entry in _cached_history(job_id):
        rows.append((USER_STATUS_LABELS.get(entry["status"], entry["status"]), entry["changed_at"]))

    html = "".join(
        f'<div class="history-row"><b>{escape(label)}</b>'
        f'<span>{escape(format_date(when))} · {escape(relative_time(when))}</span></div>'
        for label, when in rows
        if when
    )
    st.markdown(html or '<div class="mono-note">Nothing recorded yet.</div>', unsafe_allow_html=True)


def _render_delete(job_id: str, on_change):
    confirm_key = f"confirm_del_{job_id}"
    confirming = st.session_state.get(confirm_key, False)

    st.markdown('<div class="card-rule"></div>', unsafe_allow_html=True)
    if not confirming:
        del_col, _ = st.columns([3, 2])
        with del_col:
            if st.button(
                "Delete job", key=f"del_{job_id}", width="stretch", icon=":material/delete:"
            ):
                st.session_state[confirm_key] = True
                st.rerun()
        return

    st.warning("Delete this job permanently?")
    yes, no = st.columns(2)
    if yes.button("Delete", key=f"del_yes_{job_id}", width="stretch", type="primary"):
        delete_job(job_id)
        st.session_state.pop(confirm_key, None)
        _clear_detail_caches()
        if on_change:
            on_change()
        st.rerun()
    if no.button("Cancel", key=f"del_no_{job_id}", width="stretch"):
        st.session_state.pop(confirm_key, None)
        st.rerun()
