"""Companies — the two sides of one idea: firms to prioritise, firms to never see again.

The page previously did not say what either list was *for*, so neither could be
used deliberately, and it rendered three absences per card at full weight
("No description", "Careers URL not set") to convey four names. It now leads
with what each list actually does, and every row carries the numbers the jobs
table already knows: how many postings you have seen, the best score among them,
and when it was last seen.
"""

from html import escape

import streamlit as st

import library
from api import (
    add_blocked_company,
    add_starred_company,
    delete_blocked_company,
    delete_starred_company,
    update_blocked_company,
    update_starred_company,
)
from components.jobs_filters import VIEW_ALL, apply_preset
from components.jobs_list import invalidate_jobs_cache
from components.sidebar import goto
from components.styles import empty_state
from components.ui import list_toolbar, page_header, relative_time, summary_line
from library import BLOCKED, STARRED

VIEW_ALL_C = "All"
VIEW_STARRED = "★ Starred"
VIEW_BLOCKED = "🚫 Blocked"
VIEWS = [VIEW_ALL_C, VIEW_STARRED, VIEW_BLOCKED]

SORT_OPTIONS = {
    "best_score": "Best score",
    "jobs_seen": "Jobs seen",
    "recent": "Recently added",
    "name_asc": "Name A–Z",
}

# What each list actually does, stated once. Everything here is what the code
# does today, not what it sounds like it should do.
EFFECTS = (
    "**Starred** companies get a ★ in the Jobs list and their own view. "
    "Starring does not change how a job is scored.  \n"
    "**Blocked** companies are dropped the moment they are scraped, before the "
    "scorer sees them, so they never cost an LLM call. Jobs already in your list stay."
)


def _invalidate():
    library.refresh()
    invalidate_jobs_cache()


def _detail(company: dict) -> str:
    return (company.get("notes") if company["kind"] == STARRED else company.get("reason")) or ""


def _decorate(rows: list[dict]) -> list[dict]:
    stats = library.company_stats()
    out = []
    for company in rows:
        seen = stats.get(company["company_name"].strip().lower(), {})
        out.append({
            **company,
            "jobs_seen": seen.get("job_count", 0),
            "best_score": seen.get("best_score"),
            "last_seen": seen.get("last_seen"),
        })
    return out


def _matches(company: dict, needle: str) -> bool:
    haystack = " ".join(
        [company.get("company_name", ""), _detail(company), company.get("careers_url") or ""]
    )
    return needle in haystack.lower()


def _sorted(rows: list[dict], sort_key: str) -> list[dict]:
    if sort_key == "name_asc":
        return sorted(rows, key=lambda c: c["company_name"].lower())
    if sort_key == "jobs_seen":
        return sorted(rows, key=lambda c: (c["jobs_seen"], c["best_score"] or 0), reverse=True)
    if sort_key == "best_score":
        return sorted(rows, key=lambda c: (c["best_score"] or -1, c["jobs_seen"]), reverse=True)
    return sorted(rows, key=lambda c: c.get("created_at") or "", reverse=True)


# ── add ─────────────────────────────────────────────────────────────────────


@st.dialog("Add company", width="small")
def _add_company_dialog():
    # Widget state cannot be reassigned once the widget exists in the same run, so
    # the fields are emptied by moving to a new set of keys instead of clearing them.
    n = st.session_state.get("add_company_nonce", 0)

    kind = st.segmented_control(
        "List", ["★ Star", "🚫 Block"], default="★ Star", key=f"add_company_kind_{n}"
    )
    starred = kind != "🚫 Block"

    from_jobs, by_name = st.tabs(["From your jobs", "By name"])

    with from_jobs:
        _render_pick_from_jobs(n, starred)
    with by_name:
        _render_manual_add(n, starred)


def _known_names() -> set:
    return {c["company_name"].strip().lower() for c in library.companies()}


def _render_pick_from_jobs(nonce: int, starred: bool):
    """Typing "Finaira" by hand when the app already knows about Finaira is the
    kind of friction that makes a feature go unused — and hand-typed names are
    how a company list fragments into "TP" and "TP Egypt"."""
    known = _known_names()
    options = [c for name, c in library.company_stats().items() if name not in known]
    if not options:
        st.caption("Every company in your jobs table is already on one of the lists.")
        return

    picked = st.multiselect(
        "Companies in your jobs",
        options,
        format_func=lambda c: f"{c['company']}  ·  best {c['best_score']}  ·  {c['job_count']} job"
                              + ("s" if c["job_count"] != 1 else ""),
        key=f"add_company_pick_{nonce}",
        placeholder="Pick one or more",
    )
    if st.button(
        f"{'Star' if starred else 'Block'} {len(picked)} selected" if picked else "Pick a company",
        width="stretch", type="primary", disabled=not picked, key=f"add_company_bulk_{nonce}",
    ):
        added = 0
        for company in picked:
            created = (
                add_starred_company(company["company"])
                if starred
                else add_blocked_company(company["company"], "Blocked from the jobs list")
            )
            added += created is not None
        st.session_state["add_company_nonce"] = nonce + 1
        _invalidate()
        st.session_state["companies_flash"] = (
            f"{'Starred' if starred else 'Blocked'} {added} compan"
            f"{'y' if added == 1 else 'ies'}."
        )
        st.rerun()


def _render_manual_add(nonce: int, starred: bool):
    name = st.text_input("Company name *", placeholder="e.g. Google", key=f"add_company_name_{nonce}")
    if starred:
        careers_url = st.text_input(
            "Careers URL", placeholder="https://careers.company.com", key=f"add_company_url_{nonce}"
        )
        detail = st.text_area(
            "Note", placeholder="Why you want to work here",
            key=f"add_company_notes_{nonce}", height=90,
        )
    else:
        careers_url = ""
        detail = st.text_input(
            "Reason", placeholder="Agency / ghost jobs / already rejected…",
            key=f"add_company_reason_{nonce}",
        )

    cancel_col, add_col = st.columns(2)
    if cancel_col.button("Cancel", width="stretch", key=f"add_company_cancel_{nonce}"):
        st.rerun()

    if add_col.button("Add company", width="stretch", type="primary", key=f"add_company_submit_{nonce}"):
        if not name.strip():
            st.error("Company name is required.")
            return
        created = (
            add_starred_company(name.strip(), careers_url.strip() or None, detail.strip() or None)
            if starred
            else add_blocked_company(name.strip(), detail.strip() or None)
        )
        if created is None:
            st.error(f"“{name.strip()}” is already on that list, or could not be added.")
            return
        st.session_state["add_company_nonce"] = nonce + 1
        _invalidate()
        st.session_state["companies_flash"] = (
            f"{'Starred' if starred else 'Blocked'} {name.strip()}."
        )
        st.rerun()


# ── rows ────────────────────────────────────────────────────────────────────

COLUMNS = [4.2, 1.0, 1.0, 1.5, 0.8]


def _render_head():
    cols = st.columns(COLUMNS, vertical_alignment="center")
    for col, label in zip(cols, ["Company", "Jobs", "Best", "Last seen", ""]):
        col.markdown(f'<div class="list-head">{label}</div>', unsafe_allow_html=True)


def _render_row(company: dict):
    cid, kind = company["id"], company["kind"]
    row_key = f"{kind}_{cid}"
    name = company["company_name"].title()
    detail = _detail(company)
    careers_url = (company.get("careers_url") or "").strip()
    editing = st.session_state.get(f"edit_{row_key}", False)
    confirming = st.session_state.get(f"confirm_{row_key}", False)

    with st.container(border=True, key=f"companyrow_{row_key}", gap=None):
        name_col, jobs_col, score_col, seen_col, menu_col = st.columns(
            COLUMNS, vertical_alignment="center"
        )

        with name_col:
            mark = "★" if kind == STARRED else "🚫"
            mark_class = "star-mark" if kind == STARRED else "block-mark"
            link = (
                f'<a class="company-link" href="{escape(careers_url, quote=True)}" '
                f'target="_blank" rel="noopener" title="Careers page">↗</a>'
                if careers_url
                else ""
            )
            # An empty cell says "not set" better than the words do.
            note = f'<div class="company-detail">{escape(detail)}</div>' if detail else ""
            st.markdown(
                f'<div class="company-name"><span class="{mark_class}">{mark}</span>'
                f"{escape(name)}{link}</div>{note}",
                unsafe_allow_html=True,
            )

        jobs_col.markdown(
            f'<div class="cell-num">{company["jobs_seen"] or "—"}</div>', unsafe_allow_html=True
        )
        score_col.markdown(
            f'<div class="cell-num">{company["best_score"] if company["best_score"] is not None else "—"}</div>',
            unsafe_allow_html=True,
        )
        seen_col.markdown(
            f'<div class="cell-quiet">{relative_time(company["last_seen"]) or "—"}</div>',
            unsafe_allow_html=True,
        )

        with menu_col:
            with st.popover("⋯", help="Actions"):
                _render_actions(company, row_key, editing)

        if confirming:
            _render_delete_confirm(company, row_key)
        elif editing:
            _render_edit_form(company, row_key)


def _render_actions(company: dict, row_key: str, editing: bool):
    cid, kind, name = company["id"], company["kind"], company["company_name"]

    if company["jobs_seen"]:
        if st.button("See their jobs", key=f"seejobs_{row_key}", width="stretch"):
            apply_preset(VIEW_ALL)
            st.session_state["jobs_company"] = company["company_name"]
            goto("Jobs")
            st.rerun()

    if editing:
        edit_label = "Close editor"
    elif kind == STARRED and not (company.get("careers_url") or "").strip():
        edit_label = "Add careers URL"
    else:
        edit_label = "Edit"

    if st.button(edit_label, key=f"edit_btn_{row_key}", width="stretch"):
        st.session_state[f"edit_{row_key}"] = not editing
        st.rerun()

    if kind == STARRED:
        if st.button("🚫 Block instead", key=f"toblock_{row_key}", width="stretch"):
            if add_blocked_company(name, "Moved from the starred list") is not None:
                delete_starred_company(cid)
            _invalidate()
            st.session_state["companies_flash"] = f"Blocked {name.title()}."
            st.rerun()
        remove_label, done = "Remove from starred", "Removed"
    else:
        if st.button("★ Star instead", key=f"tostar_{row_key}", width="stretch"):
            if add_starred_company(name) is not None:
                delete_blocked_company(cid)
            _invalidate()
            st.session_state["companies_flash"] = f"Starred {name.title()}."
            st.rerun()
        remove_label, done = "Unblock", "Unblocked"

    if st.button(remove_label, key=f"del_{row_key}", width="stretch", icon=":material/delete:"):
        st.session_state[f"confirm_{row_key}"] = done
        st.rerun()


def _render_delete_confirm(company: dict, row_key: str):
    done = st.session_state.get(f"confirm_{row_key}")
    st.warning(f"Remove **{company['company_name'].title()}** from this list?")
    yes, no, _ = st.columns([1.4, 1.4, 4])
    if yes.button("Remove", key=f"del_yes_{row_key}", width="stretch", type="primary"):
        if company["kind"] == STARRED:
            delete_starred_company(company["id"])
        else:
            delete_blocked_company(company["id"])
        st.session_state.pop(f"confirm_{row_key}", None)
        _invalidate()
        st.session_state["companies_flash"] = f"{done} {company['company_name'].title()}."
        st.rerun()
    if no.button("Cancel", key=f"del_no_{row_key}", width="stretch"):
        st.session_state.pop(f"confirm_{row_key}", None)
        st.rerun()


def _render_edit_form(company: dict, row_key: str):
    with st.form(f"edit_form_{row_key}"):
        if company["kind"] == STARRED:
            url = st.text_input("Careers URL", value=company.get("careers_url") or "")
            notes = st.text_area("Note", value=company.get("notes") or "", height=80)
        else:
            url = ""
            notes = st.text_area("Reason", value=company.get("reason") or "", height=80)

        save, cancel, _ = st.columns([1.4, 1.4, 4])
        if save.form_submit_button("Save", width="stretch", type="primary"):
            if company["kind"] == STARRED:
                update_starred_company(
                    company["id"], careers_url=url.strip() or None, notes=notes.strip() or None
                )
            else:
                update_blocked_company(company["id"], reason=notes.strip() or None)
            st.session_state.pop(f"edit_{row_key}", None)
            _invalidate()
            st.session_state["companies_flash"] = f"Saved {company['company_name'].title()}."
            st.rerun()
        if cancel.form_submit_button("Cancel", width="stretch"):
            st.session_state.pop(f"edit_{row_key}", None)
            st.rerun()


# ── page ────────────────────────────────────────────────────────────────────


def render_companies_tab():
    (add_col,) = page_header(
        "Companies",
        "Prioritise the firms you want, and stop paying to score the ones you don't.",
        actions=1,
        action_width=1.5,
    )
    with add_col:
        if st.button(
            "Add company", width="stretch", type="primary", icon=":material/add:", key="companies_add"
        ):
            _add_company_dialog()

    companies = _decorate(library.companies())
    starred_count = sum(1 for c in companies if c["kind"] == STARRED)
    blocked_count = len(companies) - starred_count
    blocked_jobs = sum(c["jobs_seen"] for c in companies if c["kind"] == BLOCKED)

    summary_line(
        [(starred_count, "starred"), (blocked_count, "blocked")],
        trailing=(
            f"{blocked_jobs} already-scored jobs are from blocked companies"
            if blocked_jobs
            else "blocking applies to new postings only"
        ),
    )
    st.caption(EFFECTS)

    flash = st.session_state.pop("companies_flash", None)
    if flash:
        st.success(flash)

    search_col, sort_col = st.columns([5.2, 1.9], vertical_alignment="center")
    with search_col:
        search = st.text_input(
            "Search",
            key="companies_search",
            label_visibility="collapsed",
            placeholder="Search companies, notes or URLs…",
        )
    with sort_col:
        sort_key = st.selectbox(
            "Sort",
            list(SORT_OPTIONS),
            key="companies_sort",
            label_visibility="collapsed",
            format_func=lambda k: f"Sort: {SORT_OPTIONS[k]}",
        )

    counts = {VIEW_ALL_C: len(companies), VIEW_STARRED: starred_count, VIEW_BLOCKED: blocked_count}
    st.segmented_control(
        "View",
        VIEWS,
        key="companies_view",
        label_visibility="collapsed",
        format_func=lambda v: f"{v}  {counts[v]}",
        on_change=_coerce_view,
    )
    view = st.session_state.get("companies_view") or VIEW_ALL_C

    rows = companies
    if view == VIEW_STARRED:
        rows = [c for c in rows if c["kind"] == STARRED]
    elif view == VIEW_BLOCKED:
        rows = [c for c in rows if c["kind"] == BLOCKED]

    needle = search.strip().lower()
    if needle:
        rows = [c for c in rows if _matches(c, needle)]

    if not rows:
        _render_empty(view, needle, bool(companies))
        return

    list_toolbar(f"{len(rows)} compan{'y' if len(rows) == 1 else 'ies'}")
    _render_head()
    for company in _sorted(rows, sort_key):
        _render_row(company)


def _coerce_view():
    if not st.session_state.get("companies_view"):
        st.session_state["companies_view"] = VIEW_ALL_C


def _render_empty(view: str, needle: str, has_any: bool):
    if needle:
        empty_state("🔍", "No companies found", "Try a different search term.")
    elif view == VIEW_STARRED:
        empty_state(
            "★", "No starred companies",
            "Star a company and its jobs get a ★ in the list and their own view. Use "
            "<b>Add company</b> — the picker lists the companies already in your jobs table.",
        )
    elif view == VIEW_BLOCKED:
        empty_state(
            "🚫", "No blocked companies",
            "Blocked companies are dropped the moment they are scraped, so they never cost "
            "an LLM call. Block one from a job's <b>⋯</b> menu or from <b>Add company</b>.",
        )
    elif not has_any:
        empty_state(
            "🏢", "No companies yet",
            "Start from the companies already in your jobs table: press <b>Add company</b> "
            "and pick from the list.",
        )
    else:
        empty_state("🏢", "Nothing to show", "Switch views to see your companies.")
