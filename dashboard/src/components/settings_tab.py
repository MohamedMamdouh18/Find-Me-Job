"""Settings — the control room for the scraper, not a preferences pane.

Four of the five sections are verbs (run it, replace the CV, export, inspect the
runs); only Searches is settings in the traditional sense. So the page leads with
a live status strip that answers "is my scraper healthy?" before anything else,
and every action reports back what it did.
"""

import json
import os
import time
from html import escape

import streamlit as st

import library
from api import (
    delete_all_jobs,
    download_backup,
    download_cv_file,
    export_jobs,
    get_cv_info,
    get_cv_keywords,
    get_filtered_jobs,
    get_param,
    get_runs,
    put_param,
    trigger_n8n_run,
    upload_cv,
)
from components.styles import empty_state
from components.ui import (
    format_date,
    human_bytes,
    page_header,
    readout,
    relative_time,
    section_head,
    status_dot,
)

N8N_PUBLIC_URL = os.getenv("N8N_PUBLIC_URL", "http://localhost:5678")

# The LinkedIn sub-workflow reads these seven keys by name and calls .split() on
# several of them, so every row must carry all seven as strings — never null.
SEARCH_COLUMNS = [
    "Keyword",
    "Location",
    "Experience Level",
    "Remote",
    "Job Type",
    "Last Posted",
    "Easy Apply",
]
# Fixed vocabularies. These are not suggestions — the sub-workflow's URL builder
# maps each one to a LinkedIn code and silently drops anything it does not
# recognise, so free text here was a way to write a search that quietly narrows
# to nothing. Experience and Workplace go through a switch; Job Type is mapped by
# its first letter (Full-time -> F ... Other -> O), which is why "Other" works
# and an arbitrary word does not.
EXPERIENCE_OPTIONS = [
    "Internship", "Entry level", "Associate", "Mid-Senior level", "Director", "Executive",
]
REMOTE_OPTIONS = ["Remote", "Hybrid", "On-Site"]
JOB_TYPE_OPTIONS = [
    "Full-time", "Part-time", "Contract", "Temporary", "Volunteer", "Internship", "Other",
]
MULTI_COLUMNS = {
    "Experience Level": EXPERIENCE_OPTIONS,
    "Remote": REMOTE_OPTIONS,
    "Job Type": JOB_TYPE_OPTIONS,
}

# LinkedIn's f_TPR values are seconds-since-posted; nobody should have to know that.
LAST_POSTED_LABELS = {
    "": "Any time",
    "r86400": "Past 24 hours",
    "r604800": "Past week",
    "r2592000": "Past month",
}
LAST_POSTED_VALUES = {v: k for k, v in LAST_POSTED_LABELS.items()}

# Rough per-row cost of the fixed export columns, used only for a "≈" estimate.
CSV_BYTES_PER_ROW = 220
JSON_BYTES_PER_ROW = 420

HEALTH_TTL = 10


# ── cached reads ────────────────────────────────────────────────────────────


def _health() -> dict:
    """Assembled from the shared counts, never fetched here: this strip and the
    one in the sidebar must not be able to disagree about the same numbers."""
    counts = library.stats()
    hlth = library.health()
    return {
        "n8n": hlth["n8n"],
        "stats": counts,
        "last_run": hlth["last_run"],
        "queue": counts["queue"],
    }


@st.cache_data(ttl=30, show_spinner=False)
def _cached_runs(limit: int) -> list[dict]:
    return get_runs(limit)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_cv_info() -> dict:
    return get_cv_info()


@st.cache_data(ttl=60, show_spinner=False)
def _cached_keywords() -> dict:
    return get_cv_keywords()


@st.cache_data(ttl=60, show_spinner=False)
def _cached_param(name: str) -> str | None:
    return get_param(name)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_row_count(matched_only: bool) -> int:
    resp = get_filtered_jobs(
        ai_status="fit" if matched_only else None,
        user_status=None, easy_apply=None, min_score=0, search=None,
        company=None, website=None, location=None, starred_only=False,
        sort_by="updated_at", sort_order="desc", page=1, page_size=1,
    )
    return int(resp.get("total", 0))


def _invalidate_settings():
    for fn in (_cached_runs, _cached_cv_info, _cached_keywords,
               _cached_param, _cached_row_count):
        fn.clear()  # type: ignore[attr-defined]
    library.refresh()


def _flash(kind: str, msg: str):
    st.session_state["settings_flash"] = {"kind": kind, "msg": msg}


def _render_flash():
    flash = st.session_state.pop("settings_flash", None)
    if flash:
        {"success": st.success, "error": st.error, "info": st.info}.get(
            flash["kind"], st.info
        )(flash["msg"])


# ── status strip ────────────────────────────────────────────────────────────


def _n8n_state(n8n: dict) -> tuple[str, str, str]:
    """Is the n8n service itself answering — separate from whether the workflow is on."""
    host = N8N_PUBLIC_URL.split("//")[-1].rstrip("/")
    if n8n.get("reachable"):
        return "ok", "Up", host
    return "fail", "Down", f"no answer from {host}"


def _workflow_state(n8n: dict) -> tuple[str, str, str]:
    if not n8n.get("reachable"):
        return "idle", "Unknown", "n8n is not answering"
    return {
        "active": ("ok", "Active", "listening on the webhook"),
        "inactive": ("warn", "Inactive", "toggle it on in n8n"),
    }.get(n8n.get("workflow", "unknown"), ("idle", "Unknown", "set N8N_API_KEY to be sure"))


def _last_run_state(run: dict | None) -> tuple[str, str, str]:
    if not run:
        return "idle", "Never", "no run has reported in"
    when = relative_time(run.get("started_at"))
    status = run.get("status")
    if status == "running":
        return "ok", f"Running · {when}", f"{run.get('jobs_scraped', 0)} scraped so far"
    note = (
        f"{run.get('jobs_scored', 0)} scored · {run.get('jobs_matched', 0)} matched"
        f"{_duration(run.get('started_at'), run.get('finished_at'))}"
    )
    if status == "failed":
        return "fail", f"Failed · {when}", note
    return "ok", f"Done · {when}", note


@st.fragment(run_every=HEALTH_TTL)
def _status_strip():
    """Polls on its own so the page never reruns underneath the user's cursor."""
    health = _health()
    stats = health["stats"]

    wf_tone, wf_text, wf_note = _workflow_state(health["n8n"])
    n8n_tone, n8n_text, n8n_note = _n8n_state(health["n8n"])
    run_tone, run_text, run_note = _last_run_state(health["last_run"])
    total = stats.get("total", 0) or 0
    matched = stats.get("fit", 0) or 0
    queue = health["queue"]

    with st.container(border=True, key="status_strip"):
        cols = st.columns(5, gap="medium")
        cols[0].markdown(
            readout(
                "Workflow", status_dot(wf_tone, wf_text), wf_note,
                tip="Whether 'Scraping Main Workflow' is switched on in n8n. Nothing "
                    "scrapes or scores while it is off.",
                # "toggle it on in n8n" used to be advice with nowhere to go.
                link=N8N_PUBLIC_URL if wf_tone != "ok" else "",
            ),
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            readout("n8n", status_dot(n8n_tone, n8n_text), n8n_note), unsafe_allow_html=True
        )
        cols[2].markdown(
            readout("Last run", status_dot(run_tone, run_text), run_note), unsafe_allow_html=True
        )
        cols[3].markdown(
            readout(
                "Scored", f"{total:,}", f"{matched:,} matched",
                tip="Rows in the jobs table. Matched means the AI scored them at or "
                    "above your cutoff.",
            ),
            unsafe_allow_html=True,
        )
        cols[4].markdown(
            readout(
                "Queue", f"{queue:,}", "waiting to be scored" if queue else "empty",
                # 53 queued beside 10 in the database reads like a bug until you
                # know they are two different tables at two different stages.
                tip="Scraped but not yet scored. They appear under Jobs as the scorer "
                    "works through them, which only happens while the workflow is active.",
            ),
            unsafe_allow_html=True,
        )


# ── workflow ────────────────────────────────────────────────────────────────


def _duration(started: str | None, finished: str | None) -> str:
    if not started or not finished:
        return ""
    from datetime import datetime

    try:
        delta = datetime.fromisoformat(finished) - datetime.fromisoformat(started)
    except (ValueError, TypeError):
        return ""
    seconds = int(delta.total_seconds())
    return f" · {seconds}s" if seconds < 60 else f" · {seconds // 60}m {seconds % 60}s"


def _await_run(previous_id, deadline: int = 20) -> dict | None:
    """Wait for n8n to record a new run. Bounded, because a long block would
    freeze the whole session — after this the status strip takes over."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        time.sleep(2)
        runs = get_runs(1)
        if runs and runs[0].get("id") != previous_id:
            return runs[0]
    return None


def _render_workflow(health: dict):
    n8n = health["n8n"]
    reachable = bool(n8n.get("reachable"))
    inactive = n8n.get("workflow") == "inactive"

    with st.container(border=True):
        section_head(
            "Run the scraper",
            "Posts to the n8n webhook, then waits for the workflow to report back.",
        )

        blocked = not reachable or inactive
        if blocked:
            # A dead end otherwise: the strip said "toggle it on in n8n" while the
            # primary button underneath it stayed lit and would 404 on every press.
            st.warning(
                f"Can't reach n8n at {N8N_PUBLIC_URL}."
                if not reachable
                else "The webhook is not registered, so a run cannot start. Switch "
                     "**Scraping Main Workflow** to Active in n8n, then reload."
            )

        run_col, open_col, _ = st.columns([2, 2, 5], vertical_alignment="center")
        with run_col:
            run_clicked = st.button(
                "Run now",
                type="primary",
                icon=":material/play_arrow:",
                disabled=blocked,
                width="stretch",
                help=(
                    f"Can't reach n8n at {N8N_PUBLIC_URL}"
                    if not reachable
                    else "Activate the workflow in n8n first"
                    if inactive
                    else None
                ),
                key="run_now",
            )
        with open_col:
            st.link_button(
                "Activate in n8n" if blocked else "Open in n8n",
                N8N_PUBLIC_URL,
                width="stretch",
                icon=":material/open_in_new:",
                type="primary" if blocked else "secondary",
            )

        if run_clicked:
            _do_run(health)

        error = st.session_state.get("run_error")
        if error:
            _render_run_failure(error)

        st.markdown('<div class="card-rule"></div>', unsafe_allow_html=True)
        _render_last_run(health["last_run"])


def _do_run(health: dict):
    st.session_state.pop("run_error", None)
    previous = (health["last_run"] or {}).get("id")

    with st.status("Starting run…", expanded=True) as status:
        st.write("Posting to the n8n webhook…")
        ok, msg = trigger_n8n_run()
        if not ok:
            status.update(label="Run failed", state="error")
            st.session_state["run_error"] = msg
            _invalidate_settings()
            # Rerun so the persistent failure block is the only thing on screen —
            # a collapsed status transcript beside it says the same thing twice.
            st.rerun()

        st.write("Accepted. Waiting for n8n to record the run…")
        run = _await_run(previous)
        _invalidate_settings()
        if run:
            status.update(label=f"Run #{run['id']} started", state="complete")
            st.write(f"n8n reported run #{run['id']} ({run.get('trigger', 'manual')}).")
            st.toast(f"Run #{run['id']} started", icon="✅")
        else:
            status.update(label="Accepted — still starting", state="complete")
            st.write(
                "n8n took the request but has not recorded a run yet. "
                "Progress shows up in the status strip and under History."
            )
            st.toast("Run triggered", icon="✅")


def _render_run_failure(msg: str):
    with st.container(border=True, key="run_failure"):
        st.markdown(
            f'<div class="failure-title">Run failed</div>'
            f'<div class="failure-body">{escape(msg)}</div>'
            '<div class="failure-body">The workflow may be inactive in n8n, or the '
            "container may be down.</div>",
            unsafe_allow_html=True,
        )
        a, b, _ = st.columns([2, 2, 5])
        with a:
            st.link_button(
                "Open in n8n", N8N_PUBLIC_URL, width="stretch", icon=":material/open_in_new:"
            )
        with b:
            if st.button("Dismiss", width="stretch", key="dismiss_run_error"):
                st.session_state.pop("run_error", None)
                st.rerun()


def _render_last_run(run: dict | None):
    st.markdown('<div class="detail-label">Last run</div>', unsafe_allow_html=True)
    if not run:
        st.markdown(
            '<div class="mono-note">No run has reported in yet.</div>', unsafe_allow_html=True
        )
        return
    tone, text, note = _last_run_state(run)
    st.markdown(
        f'<div class="mono-note">{status_dot(tone, text)}'
        f'<span class="mono-sep">·</span>{escape(note)}</div>',
        unsafe_allow_html=True,
    )


# ── CV ──────────────────────────────────────────────────────────────────────


def _render_cv():
    info = _cached_cv_info()

    with st.container(border=True):
        section_head("Current CV", "The document every job is scored against.")
        if not info.get("exists"):
            empty_state(
                "📄", "No CV uploaded",
                "Scoring cannot run without one. Upload a <b>.docx</b> below to start matching.",
            )
        else:
            modified = info.get("modified_at")
            absolute = format_date(_from_epoch(modified))
            since = relative_time(_from_epoch(modified))
            # The keyword line below reports a different event, so both say which
            # one they mean rather than printing two ages for "updated".
            st.markdown(
                f'<div class="mono-note">cv.docx<span class="mono-sep">·</span>'
                f"{human_bytes(info.get('bytes'))}<span class=\"mono-sep\">·</span>"
                f"file changed {escape(absolute)} ({escape(since)})</div>",
                unsafe_allow_html=True,
            )

            dl_col, _ = st.columns([2, 7])
            with dl_col:
                st.download_button(
                    "Download",
                    data=download_cv_file,
                    file_name="cv.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    width="stretch",
                    icon=":material/download:",
                    key="cv_download",
                )

        _render_keywords()

        with st.expander("Replace CV"):
            _render_cv_upload(info)


def _from_epoch(value):
    from datetime import datetime

    try:
        return datetime.fromtimestamp(float(value)).isoformat()
    except (TypeError, ValueError):
        return None


def _render_keywords():
    st.markdown('<div class="detail-label">Extracted keywords</div>', unsafe_allow_html=True)
    row = _cached_keywords()
    raw = row.get("keywords")
    if not raw:
        st.markdown(
            '<div class="mono-note">None yet — they are extracted on the first run '
            "after a CV change.</div>",
            unsafe_allow_html=True,
        )
        return

    try:
        parsed = json.loads(raw)
        titles = [str(t) for t in parsed.get("titles", [])]
        skills = [str(s) for s in parsed.get("skills", [])]
    except (ValueError, AttributeError):
        st.markdown(
            '<div class="mono-note">Stored keywords are not valid JSON.</div>',
            unsafe_allow_html=True,
        )
        return

    tags = "".join(f'<span class="tag tag-strong">{escape(t)}</span>' for t in titles[:6])
    tags += "".join(f'<span class="tag">{escape(s)}</span>' for s in skills[:18])
    extra = max(0, len(skills) - 18)
    if extra:
        tags += f'<span class="tag tag-quiet">+{extra} more</span>'
    st.markdown(f'<div class="tag-row">{tags}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="mono-note">{len(titles)} titles<span class="mono-sep">·</span>'
        f'{len(skills)} skills<span class="mono-sep">·</span>'
        f"extracted {escape(relative_time(row.get('updated_at')))}</div>",
        unsafe_allow_html=True,
    )


def _render_cv_upload(info: dict):
    uploaded = st.file_uploader("Replace cv.docx", type=["docx"], key="cv_uploader")
    if uploaded is None:
        st.caption("Only .docx is parsed — .pdf and .doc are not read by the extractor.")
        return

    old_size = human_bytes(info.get("bytes")) if info.get("exists") else "—"
    st.markdown(
        f'<div class="mono-note">{escape(uploaded.name)}<span class="mono-sep">·</span>'
        f"{old_size} → {human_bytes(len(uploaded.getvalue()))}</div>",
        unsafe_allow_html=True,
    )
    confirm_col, _ = st.columns([2, 5])
    with confirm_col:
        if st.button("Replace", type="primary", width="stretch", key="cv_replace"):
            ok, msg = upload_cv(uploaded.name, uploaded.getvalue())
            _invalidate_settings()
            if ok:
                _flash("success", f"CV replaced — {msg}. Keywords re-extract on the next run.")
            else:
                _flash("error", f"Upload failed: {msg}")
            st.rerun()


# ── searches ────────────────────────────────────────────────────────────────


def _searches_to_rows(raw: str | None) -> tuple[list[dict], str | None]:
    if raw is None:
        return [], "Could not read params/linkedin_searches.txt from the API."
    try:
        parsed = json.loads(raw)
        searches = parsed["searches"]
        if not isinstance(searches, list):
            raise ValueError("`searches` must be a list")
    except (ValueError, KeyError, TypeError) as e:
        return [], f"Invalid JSON: {e}"

    rows = []
    for entry in searches:
        entry = entry if isinstance(entry, dict) else {}
        last_posted = str(entry.get("Last Posted", "") or "")
        rows.append(
            {
                "Keyword": str(entry.get("Keyword", "") or ""),
                "Location": str(entry.get("Location", "") or ""),
                **{
                    name: _split_values(entry.get(name)) for name in MULTI_COLUMNS
                },
                "Last Posted": LAST_POSTED_LABELS.get(last_posted, last_posted),
                "Easy Apply": bool(str(entry.get("Easy Apply", "") or "").strip()),
            }
        )
    return rows, None


def _split_values(raw) -> list[str]:
    """The file stores these as one comma-separated string; the editor wants a list."""
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def _multi_options(rows: list[dict], name: str) -> list[str]:
    """The canonical vocabulary, plus anything already in the file that is not in
    it — dropping a stored value the moment the tab is opened would edit the
    user's searches without being asked to."""
    options = list(MULTI_COLUMNS[name])
    for row in rows:
        for value in row.get(name) or []:
            if value not in options:
                options.append(value)
    return options


def _posted_options(rows: list[dict]) -> list[str]:
    """Keep any raw f_TPR value already in the file as a selectable option, or the
    editor would silently blank it on the next save."""
    options = list(LAST_POSTED_LABELS.values())
    for row in rows:
        value = str(row.get("Last Posted") or "")
        if value and value not in options:
            options.append(value)
    return options


def _rows_to_json(rows: list[dict]) -> str:
    searches = []
    for row in rows:
        keyword = str(row.get("Keyword") or "").strip()
        location = str(row.get("Location") or "").strip()
        if not keyword and not location:
            continue  # a row with neither builds a bare LinkedIn URL
        label = str(row.get("Last Posted") or "")
        searches.append(
            {
                "Keyword": keyword,
                "Location": location,
                # Back to the comma-separated strings the sub-workflow splits on.
                **{name: _join_values(row.get(name)) for name in MULTI_COLUMNS},
                "Last Posted": LAST_POSTED_VALUES.get(label, label),
                # The sub-workflow only checks for a non-empty string here.
                "Easy Apply": "true" if row.get("Easy Apply") else "",
            }
        )
    return json.dumps({"searches": searches}, indent=2, ensure_ascii=False)


def _join_values(value) -> str:
    if isinstance(value, str):
        return value.strip()
    return ", ".join(str(v).strip() for v in (value or []) if str(v).strip())


def _render_searches():
    raw = _cached_param("linkedin_searches")
    rows, error = _searches_to_rows(raw)

    with st.container(border=True):
        if error:
            section_head("LinkedIn searches", "One row per LinkedIn query.")
            st.error(error)
            return

        # The heading reports whether there are unsaved changes, which is only
        # knowable after the editor has run, so its slot is reserved up front.
        head_slot = st.container()

        # Deliberately not wrapped in st.form: a form batches its widgets, so the
        # editor's value is unknown until submit, and "Save changes" could only
        # ever be permanently enabled. Outside one, the edit is readable now and
        # the button can tell you whether there is anything to save.
        edited = st.data_editor(
            rows,
            num_rows="dynamic",
            width="stretch",
            key="searches_editor",
            column_config={
                "Keyword": st.column_config.TextColumn(
                    "Keyword", width="medium", help="Free text, as typed into LinkedIn"
                ),
                "Location": st.column_config.TextColumn("Location", width="small"),
                "Experience Level": st.column_config.MultiselectColumn(
                    "Experience", width="medium",
                    options=_multi_options(rows, "Experience Level"),
                    help="Pick any number. Leave empty for every level.",
                ),
                "Remote": st.column_config.MultiselectColumn(
                    "Workplace", width="medium",
                    options=_multi_options(rows, "Remote"),
                    help="Pick any number. Leave empty for every arrangement.",
                ),
                "Job Type": st.column_config.MultiselectColumn(
                    "Job type", width="medium",
                    options=_multi_options(rows, "Job Type"),
                    help="Pick any number. Leave empty for every type.",
                ),
                "Last Posted": st.column_config.SelectboxColumn(
                    "Posted within",
                    options=_posted_options(rows),
                    width="small",
                ),
                "Easy Apply": st.column_config.CheckboxColumn("Easy apply", width="small"),
            },
        )

        content = _rows_to_json(list(edited))
        dirty = content.strip() != (raw or "").strip()
        with head_slot:
            section_head(
                "LinkedIn searches",
                "One row per LinkedIn query. Each runs on every scrape.",
                state=(
                    '<span class="unsaved">● Unsaved changes</span>'
                    if dirty
                    else f'<span class="mono">{len(rows)} configured</span>'
                ),
            )

        save_col, _ = st.columns([2, 6])
        with save_col:
            if st.button(
                "Save changes", type="primary", width="stretch", disabled=not dirty,
                key="searches_save", help=None if dirty else "Nothing has changed",
            ):
                ok, msg = put_param("linkedin_searches", content)
                _invalidate_settings()
                _flash("success" if ok else "error",
                       "Searches saved." if ok else f"Save failed: {msg}")
                st.rerun()

    _render_prompt_editor()


def _render_prompt_editor():
    name = "llm_keywords_extract"
    current = _cached_param(name)

    with st.container(border=True):
        if current is None:
            section_head("CV keyword extraction prompt", "")
            st.error(f"Could not read params/{name}.txt from the API.")
            return

        head_slot = st.container()
        edited = st.text_area(
            "Prompt", value=current, height=260, key="prompt_edit",
            label_visibility="collapsed",
        )
        dirty = edited.strip() != current.strip()
        with head_slot:
            section_head(
                "CV keyword extraction prompt",
                "Sent with your CV text to derive the titles and skills RemoteOK is "
                "filtered on.",
                state=(
                    '<span class="unsaved">● Unsaved changes</span>'
                    if dirty
                    else f'<span class="mono">{len(current):,} characters</span>'
                ),
            )

        save_col, _ = st.columns([2, 6])
        with save_col:
            if st.button(
                "Save changes", type="primary", width="stretch", disabled=not dirty,
                key="prompt_save", help=None if dirty else "Nothing has changed",
            ):
                ok, msg = put_param(name, edited)
                _invalidate_settings()
                _flash("success" if ok else "error",
                       "Prompt saved." if ok else f"Save failed: {msg}")
                st.rerun()


# ── data ────────────────────────────────────────────────────────────────────


def _render_data():
    with st.container(border=True):
        section_head("Export", "Take the jobs table out as a file.")

        fmt_col, scope_col = st.columns([2, 3], vertical_alignment="bottom")
        with fmt_col:
            fmt = st.segmented_control(
                "Format", ["CSV", "JSON"], default="CSV", key="export_format"
            ) or "CSV"
        with scope_col:
            scope = st.selectbox(
                "Scope", ["Matched jobs", "All jobs"], key="export_scope"
            )

        matched_only = scope == "Matched jobs"
        rows = _cached_row_count(matched_only)
        per_row = CSV_BYTES_PER_ROW if fmt == "CSV" else JSON_BYTES_PER_ROW
        st.markdown(
            f'<div class="mono-note">{rows:,} rows<span class="mono-sep">·</span>'
            f"≈ {human_bytes(rows * per_row)}</div>",
            unsafe_allow_html=True,
        )

        dl_col, _ = st.columns([2, 6])
        with dl_col:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            st.download_button(
                "Download",
                # A callable defers generation to the click, so opening the tab
                # never exports the whole table speculatively.
                data=lambda: _export_payload(fmt, matched_only),
                file_name=f"jobs-{stamp}.{fmt.lower()}",
                mime="text/csv" if fmt == "CSV" else "application/json",
                type="primary",
                width="stretch",
                disabled=rows == 0,
                icon=":material/download:",
                key="export_download",
            )
        st.caption("Matched jobs are the ones the AI scored as a fit.")

    with st.container(border=True):
        section_head("Backup", "A consistent snapshot of the whole database.")
        st.markdown(
            '<div class="mono-note">jobs.db<span class="mono-sep">·</span>'
            "safe to take while the stack is running</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Backups stream straight to your browser and are not kept on the server, "
            "so there is no history here to list."
        )
        b_col, _ = st.columns([2, 6])
        with b_col:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            st.download_button(
                "Create backup",
                data=_backup_payload,
                file_name=f"jobs-backup-{stamp}.db",
                mime="application/octet-stream",
                width="stretch",
                icon=":material/database:",
                key="backup_download",
            )

    _render_danger_zone()


def _export_payload(fmt: str, matched_only: bool) -> bytes:
    """Runs at click time, not at render time — no caching layer here, because the
    callable is invoked outside a normal script run."""
    data = export_jobs(fmt.lower(), include_body=False, ai_status="fit" if matched_only else None)
    return data or b''


def _backup_payload() -> bytes:
    data = download_backup()
    return data or b""


# ── danger zone ─────────────────────────────────────────────────────────────

CLEAR_PHRASE = "delete all jobs"


@st.dialog("Clear all jobs", width="small")
def _clear_jobs_dialog(total: int):
    st.markdown(
        f"This deletes **{total:,} jobs** and their status history. "
        "Starred and blocked companies, your CV and your searches are not affected."
    )
    st.caption("Scraped jobs are re-discoverable, but anything you typed by hand is not.")
    typed = st.text_input(
        f"Type “{CLEAR_PHRASE}” to confirm", key="clear_phrase", placeholder=CLEAR_PHRASE
    )
    cancel_col, go_col = st.columns(2)
    if cancel_col.button("Cancel", width="stretch", key="clear_cancel"):
        st.rerun()
    if go_col.button(
        "Delete", type="primary", width="stretch",
        disabled=typed.strip().lower() != CLEAR_PHRASE, key="clear_go",
    ):
        ok, msg = delete_all_jobs()
        _invalidate_settings()
        st.cache_data.clear()
        _flash("success" if ok else "error", msg)
        st.rerun()


def _render_danger_zone():
    total = _cached_row_count(False)
    with st.container(border=True, key="danger_zone"):
        section_head("Danger zone", "Irreversible. Take a backup first.")
        d_col, note_col = st.columns([2, 6], vertical_alignment="center")
        with d_col:
            if st.button(
                "Clear all jobs", width="stretch", disabled=total == 0,
                icon=":material/delete_forever:", key="clear_all_jobs",
            ):
                _clear_jobs_dialog(total)
        with note_col:
            st.markdown(
                f'<div class="mono-note">{total:,} jobs would be deleted</div>',
                unsafe_allow_html=True,
            )


# ── history ─────────────────────────────────────────────────────────────────

STATUS_GLYPH = {"success": "✓ Done", "failed": "✗ Failed", "running": "⟳ Running"}


def _render_history():
    runs = _cached_runs(50)

    with st.container(border=True):
        section_head("Run history", "Every run the workflow has reported.")

        if not runs:
            empty_state(
                "📋", "No runs recorded yet",
                "Runs appear here once the workflow reports in. If you have already run it "
                "from n8n, check that <b>Scraping Main Workflow</b> is Active and that its "
                "<b>Start Run</b> and <b>Finish Run</b> nodes point at "
                "<code>http://python-api:8001/api/runs</code>.",
            )
            go_col, _ = st.columns([2, 6])
            with go_col:
                if st.button(
                    "Go to Workflow", width="stretch", icon=":material/play_arrow:",
                    key="history_to_workflow",
                ):
                    _flash("info", "Use Run now on the Workflow tab to start a run.")
                    st.rerun()
            return

        only_failed = st.toggle("Failed runs only", key="history_failed_only")
        shown = [r for r in runs if r.get("status") == "failed"] if only_failed else runs

        chart = [r for r in reversed(runs[:14])]
        if len(chart) > 1:
            st.markdown(
                '<div class="detail-label">Jobs matched per run (last 14)</div>',
                unsafe_allow_html=True,
            )
            st.line_chart(
                {"matched": [r.get("jobs_matched", 0) or 0 for r in chart]},
                height=120, color="#2a78d6",
            )

        table = [
            {
                "Started": (r.get("started_at") or "").replace("T", " ")[:16],
                "Status": STATUS_GLYPH.get(r.get("status"), r.get("status", "")),
                "Took": _duration(r.get("started_at"), r.get("finished_at")).lstrip(" ·") or "—",
                "Trigger": r.get("trigger", ""),
                "Scraped": r.get("jobs_scraped", 0),
                "Scored": r.get("jobs_scored", 0),
                "Matched": r.get("jobs_matched", 0),
            }
            for r in shown
        ]
        event = st.dataframe(
            table,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="runs_table",
        )

        selected = (event.selection or {}).get("rows") or []
        if selected:
            _render_run_detail(shown[selected[0]])


def _render_run_detail(run: dict):
    st.markdown('<div class="detail-label">Run detail</div>', unsafe_allow_html=True)
    lines = [
        f"run_id      {run.get('id')}",
        f"trigger     {run.get('trigger')}",
        f"status      {run.get('status')}",
        f"started_at  {run.get('started_at')}",
        f"finished_at {run.get('finished_at') or '—'}",
        f"scraped     {run.get('jobs_scraped', 0)}",
        f"scored      {run.get('jobs_scored', 0)}",
        f"matched     {run.get('jobs_matched', 0)}",
    ]
    st.code("\n".join(lines), language=None)
    if run.get("error"):
        st.error(run["error"])


# ── page ────────────────────────────────────────────────────────────────────


def render_settings_tab():
    with st.container(key="settings_page"):
        page_header("Settings", "Workflow control, CV, searches, data and run history.")
        _render_flash()
        _status_strip()

        workflow, cv, searches, data, history = st.tabs(
            ["Workflow", "CV", "Searches", "Data", "History"]
        )
        with workflow:
            _render_workflow(_health())
        with cv:
            _render_cv()
        with searches:
            _render_searches()
        with data:
            _render_data()
        with history:
            _render_history()
