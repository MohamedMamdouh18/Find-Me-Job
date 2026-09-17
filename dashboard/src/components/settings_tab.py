"""Settings — the control room for the scraper, not a preferences pane.

Four of the six tabs are verbs (run it, replace the CV, export, inspect the runs);
Config and Searches are settings in the traditional sense. So the page leads with
a live status strip that answers "is my scraper healthy?" before anything else,
and every action reports back what it did.
"""

import json
import os
import time
from datetime import datetime
from datetime import time as clock_time
from html import escape

import streamlit as st

import library
from api import (
    delete_all_jobs,
    download_backup,
    download_cv_file,
    export_jobs,
    get_current_run,
    get_cv_info,
    delete_cv_keywords,
    get_cv_keywords,
    get_filtered_jobs,
    get_param,
    get_run_events,
    get_runs,
    get_schedule,
    get_sources,
    pause_run,
    put_param,
    put_schedule,
    put_settings,
    put_source,
    resume_run,
    send_email,
    stop_run,
    test_notification,
    trigger_run,
    update_cv_keywords,
    upload_cv,
)
from constants import BLUE
from components.styles import empty_state
from components.ui import (
    format_date,
    parse_ts,
    human_bytes,
    page_header,
    readout,
    relative_time,
    section_head,
    status_dot,
)

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
        "current_run": hlth.get("current_run"),
        "stats": counts,
        "last_run": hlth.get("last_run"),
        "queue": counts["queue"],
    }


@st.cache_data(ttl=30, show_spinner=False)
def _cached_runs(limit: int) -> list[dict]:
    return get_runs(limit)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_schedule() -> dict:
    return get_schedule()


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


@st.cache_data(ttl=30, show_spinner=False)
def _cached_sources() -> list[dict]:
    return get_sources()


def _invalidate_settings():
    for fn in (_cached_runs, _cached_cv_info, _cached_keywords,
               _cached_param, _cached_row_count, _cached_schedule, _cached_sources):
        fn.clear()  # type: ignore[attr-defined]
    library.refresh()


def _flash(kind: str, msg: str):
    st.session_state["settings_flash"] = {"kind": kind, "msg": msg}


def _render_flash():
    flash = st.session_state.pop("settings_flash", None)
    if flash:
        {"success": st.success, "error": st.error, "info": st.info, "warning": st.warning}.get(
            flash["kind"], st.info
        )(flash["msg"])


# ── status strip ────────────────────────────────────────────────────────────


def _last_run_state(run: dict | None) -> tuple[str, str, str]:
    if not run:
        return "idle", "Never", "no run has reported in"
    status = run.get("status")
    if status == "running":
        started = relative_time(run.get("started_at"))
        return "ok", f"Running · {started}", f"{run.get('jobs_scraped', 0)} scraped so far"
    # Done/Failed/Paused all name the moment the run ENDED, so they read finished_at.
    # started_at would make an 8h run that stopped a minute ago read "8 hours ago".
    when = relative_time(run.get("finished_at") or run.get("started_at"))
    note = (
        f"{run.get('jobs_scored', 0)} scored · {run.get('jobs_matched', 0)} matched"
        f"{_duration(run.get('started_at'), run.get('finished_at'))}"
    )
    if status == "failed":
        return "fail", f"Failed · {when}", note
    if status == "paused":
        return "warn", f"Paused · {when}", note
    if status == "stopped":
        return "warn", f"Stopped · {when}", note
    return "ok", f"Done · {when}", note


def _pipeline_state(curr: dict | None, last: dict | None) -> tuple[str, str, str]:
    if curr:
        stage = curr.get("stage", "running")
        detail = curr.get("detail", "In progress")
        return "ok", f"Running · {stage}", detail
    if not last:
        return "idle", "Ready", "No run recorded yet"
    # Same rule as _last_run_state: these labels describe a finished run.
    when = relative_time(last.get("finished_at") or last.get("started_at"))
    if last.get("status") == "failed":
        return "fail", f"Failed · {when}", last.get("error") or "Check run history"
    if last.get("status") == "paused":
        return "warn", f"Paused · {when}", "Resume from the Workflow tab"
    if last.get("status") == "stopped":
        return "warn", f"Stopped · {when}", "Start a fresh run when ready"
    return "ok", f"Ready · {when}", f"{last.get('jobs_scored', 0)} scored · {last.get('jobs_matched', 0)} matched"


@st.fragment(run_every=HEALTH_TTL)
def _status_strip():
    """Polls on its own so the page never reruns underneath the user's cursor."""
    health = _health()
    stats = health["stats"]
    curr = health.get("current_run")
    last = health.get("last_run")

    pipe_tone, pipe_text, pipe_note = _pipeline_state(curr, last)
    run_tone, run_text, run_note = _last_run_state(last)
    total = stats.get("total", 0) or 0
    matched = stats.get("fit", 0) or 0
    queue = health["queue"]

    with st.container(border=True, key="status_strip"):
        cols = st.columns(4, gap="medium")
        cols[0].markdown(
            readout("Pipeline", status_dot(pipe_tone, pipe_text), pipe_note),
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            readout("Last run", status_dot(run_tone, run_text), run_note),
            unsafe_allow_html=True,
        )
        cols[2].markdown(
            readout(
                "Scored",
                f"{total:,}",
                f"{matched:,} matched",
                tip="Matched: scored at or above your cutoff.",
            ),
            unsafe_allow_html=True,
        )
        cols[3].markdown(
            readout(
                "Queue",
                f"{queue:,}",
                "waiting to be scored" if queue else "empty",
                tip="Scraped jobs waiting to be scored.",
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


PAUSE_TIP = (
    "Finishes the current job, then pauses. Resume continues the queue."
)

STOP_TIP = (
    "Ends the run now; the current job's result is lost. Cannot be resumed."
)


def _action_button(
    label: str,
    key: str,
    icon: str,
    call,
    toast: str,
    error_prefix: str,
    *,
    primary: bool = False,
    invalidate: bool = False,
    tooltip: str | None = None,
) -> None:
    """Every pipeline control has the same shape: fire the call, report the outcome,
    rerun. `call` returns the (ok, message) pair the api module hands back."""
    kind = {"type": "primary"} if primary else {}
    if not st.button(label, icon=icon, width="stretch", key=key, help=tooltip, **kind):
        return
    ok, msg = call()
    if ok:
        st.toast(toast, icon="✅")
    else:
        st.error(f"{error_prefix}: {msg}")
    if invalidate:
        _invalidate_settings()
    st.rerun()


@st.fragment(run_every=2)
def _render_workflow():
    # Read inside the fragment, never passed in: a fragment reruns with the arguments
    # captured at the last full app run, so a health dict taken as a parameter would
    # freeze while curr kept refreshing. The running -> paused transition would then
    # render the idle "Run now" panel instead of Resume until something reran the page.
    curr = get_current_run()

    # Clears the history table and the last-run panel as well as the shared counts,
    # which is why this clears more than the sidebar does.
    if library.run_ended(curr is not None, "workflow"):
        _invalidate_settings()

    health = _health()
    with st.container(border=True):
        section_head(
            "Job Pipeline",
            "Scrapes your sources and scores new jobs against your CV.",
        )

        if curr:
            stage = curr.get("stage", "running")
            detail = curr.get("detail", "")
            done = curr.get("done", 0)
            total = curr.get("total", 0)
            rem = curr.get("seconds_remaining")

            st.markdown(f"### Running: `{stage}`")
            st.markdown(f"**{escape(detail)}**")

            if rem is not None and rem > 0:
                st.info(f"Next scoring call in {rem}s")

            if total > 0:
                pct = min(1.0, max(0.0, done / total))
                st.progress(pct, text=f"{done} of {total} completed")

            events = curr.get("events", [])
            if events:
                st.markdown('<div class="detail-label">Recent events</div>', unsafe_allow_html=True)
                for ev in reversed(events):
                    lvl = ev.get("level", "info")
                    st.text(f"[{ev.get('stage')}] ({lvl}) {ev.get('message')}")

            st.markdown('<div class="card-rule"></div>', unsafe_allow_html=True)
            if curr.get("stop_requested"):
                st.warning("Stopping — ending the run now.",
                           icon=":material/stop_circle:")
            elif curr.get("pause_requested"):
                # A toast vanishes in seconds while the pause waits for the current
                # LLM call to return, which reads as "the click did nothing".
                st.warning(
                    "Pausing after the current step finishes.",
                    icon=":material/pause_circle:",
                )
            else:
                pause_col, stop_col, _ = st.columns(
                    [2, 2, 3], vertical_alignment="center"
                )
                with pause_col:
                    _action_button(
                        "Pause", "pause_run", ":material/pause:", pause_run,
                        "Pausing after the current job", "Could not pause",
                        tooltip=PAUSE_TIP,
                    )
                with stop_col:
                    _action_button(
                        "Stop", "stop_run", ":material/stop:", stop_run,
                        "Stopping now", "Could not stop",
                        tooltip=STOP_TIP,
                    )
                st.caption("Pause can be resumed. Stop cannot.")
        elif (health.get("last_run") or {}).get("status") == "paused":
            queued = health.get("queue", 0)
            st.markdown("### Paused")
            st.markdown(
                f"**{queued:,} job{'' if queued == 1 else 's'} still queued.** "
                "Scheduled runs are skipped while paused."
            )
            resume_col, fresh_col, _ = st.columns([2, 2, 3], vertical_alignment="center")
            with resume_col:
                _action_button(
                    "Resume", "resume_run", ":material/play_arrow:", resume_run,
                    "Resuming the queue", "Could not resume",
                    primary=True, invalidate=True,
                )
            with fresh_col:
                _action_button(
                    "Start fresh run", "fresh_run", ":material/refresh:", trigger_run,
                    "Fresh run started in background", "Failed to start run",
                    invalidate=True,
                )
            st.caption("Resume scores the queue. Start fresh run scrapes again first.")

            st.markdown('<div class="card-rule"></div>', unsafe_allow_html=True)
            _render_last_run(health.get("last_run"))
        else:
            run_col, _ = st.columns([2, 5], vertical_alignment="center")
            with run_col:
                _action_button(
                    "Run now", "run_now", ":material/play_arrow:", trigger_run,
                    "Run started in background", "Failed to start run",
                    primary=True,
                    tooltip="Scrapes enabled sources and scores new jobs, in the background.",
                )
            _render_run_readiness()

            st.markdown('<div class="card-rule"></div>', unsafe_allow_html=True)
            _render_last_run(health.get("last_run"))


def _render_run_readiness():
    """What would make Run now pointless, said before the user presses it."""
    missing = []
    if not _cached_cv_info().get("exists"):
        missing.append("upload your CV on the **CV** tab")
    if not (library.settings().get("LLM_API_KEY") or {}).get("set"):
        missing.append("add an AI **API key** on the **Config** tab")
    if missing:
        st.warning("Before running: " + " and ".join(missing) + ".")


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
                "Upload a <b>.docx</b> below to start scoring.",
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

        _render_keywords(bool(info.get("exists")))

        # Open by default when there is no CV: uploading is the only thing to do here.
        with st.expander("Replace CV" if info.get("exists") else "Upload CV",
                         expanded=not info.get("exists")):
            _render_cv_upload(info)


def _from_epoch(value):
    from datetime import datetime

    try:
        return datetime.fromtimestamp(float(value)).isoformat()
    except (TypeError, ValueError):
        return None


KEYWORDS_EXPLAINED = (
    "Decide which RemoteOK, Himalayas and We Work Remotely jobs get scored. "
    "They don't change the score."
)


def _render_keywords(cv_exists: bool):
    st.markdown('<div class="detail-label">CV keywords</div>', unsafe_allow_html=True)
    st.caption(KEYWORDS_EXPLAINED)
    row = _cached_keywords()
    raw = row.get("keywords")

    titles: list[str] = []
    skills: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
            titles = [str(t) for t in parsed.get("titles", [])]
            skills = [str(s) for s in parsed.get("skills", [])]
        except (ValueError, AttributeError):
            st.warning("The stored keywords are unreadable. Save new ones below, or re-extract them.")

    if not cv_exists:
        st.markdown(
            '<div class="mono-note">Upload a CV first.</div>',
            unsafe_allow_html=True,
        )
        return

    if raw:
        st.markdown(
            f'<div class="mono-note">{len(titles)} titles<span class="mono-sep">·</span>'
            f'{len(skills)} skills<span class="mono-sep">·</span>'
            f"updated {escape(relative_time(row.get('updated_at')))}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="mono-note">None yet. Extracted on the next run, or add your own.</div>',
            unsafe_allow_html=True,
        )

    # Keyed on the stored version so a save or re-extract shows the new lists instead
    # of the widget state left over from before.
    version = row.get("updated_at") or "none"
    with st.form(f"cv_keywords_form_{version}", border=False):
        new_titles = st.multiselect(
            "Job titles",
            options=titles,
            default=titles,
            accept_new_options=True,
            placeholder="Type a job title and press Enter",
            help="Roles you want, e.g. Backend Engineer. Feed jobs with a matching title are kept.",
        )
        new_skills = st.multiselect(
            "Skills",
            options=skills,
            default=skills,
            accept_new_options=True,
            placeholder="Type a skill and press Enter",
            help="Tools and technologies, e.g. Python. Feed jobs mentioning two or more are kept.",
        )
        st.caption("Replacing the CV re-extracts and overwrites these.")
        save_col, _ = st.columns([2, 5])
        submitted = save_col.form_submit_button(
            "Save keywords", type="primary", width="stretch", icon=":material/save:"
        )

    if submitted:
        ok, msg = update_cv_keywords(new_titles, new_skills)
        _invalidate_settings()
        if not ok:
            _flash("error", f"Could not save keywords: {msg}")
        elif not (new_titles or new_skills):
            _flash("warning", "Keywords cleared. Feed jobs are dropped until you add some.")
        else:
            _flash("success", f"Saved {len(new_titles)} titles and {len(new_skills)} skills. "
                              "They apply from the next run.")
        st.rerun()

    if raw:
        _render_reextract()


def _render_reextract():
    key = "cv_keywords_reextract_confirm"
    if not st.session_state.get(key):
        if st.button(
            "Re-extract from CV",
            icon=":material/restart_alt:",
            key="cv_keywords_reextract",
            help="Discards these keywords and your edits; the next run extracts them again.",
        ):
            st.session_state[key] = True
            st.rerun()
        return

    st.warning("Delete these keywords? Your edits are lost; the next run re-extracts them.")
    yes_col, no_col, _ = st.columns([1.4, 1.4, 4])
    if yes_col.button("Delete", type="primary", width="stretch", key="cv_keywords_reextract_yes"):
        st.session_state.pop(key, None)
        ok = delete_cv_keywords()
        _invalidate_settings()
        _flash("success" if ok else "error",
               "Keywords deleted. The next run extracts them from your CV."
               if ok else "Could not delete the keywords.")
        st.rerun()
    if no_col.button("Cancel", width="stretch", key="cv_keywords_reextract_no"):
        st.session_state.pop(key, None)
        st.rerun()


def _render_cv_upload(info: dict):
    uploaded = st.file_uploader("Replace cv.docx", help="Keywords are re-extracted on the next run.",
                                type=["docx"], key="cv_uploader")
    if uploaded is None:
        st.caption("Only .docx is supported.")
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
                "Location": st.column_config.TextColumn(
                    "Location", width="small",
                    help="City or country, e.g. Berlin. Empty for anywhere.",
                ),
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
                    help="Only postings newer than this.",
                ),
                "Easy Apply": st.column_config.CheckboxColumn(
                    "Easy apply", width="small",
                    help="Only LinkedIn one-click apply postings.",
                ),
            },
        )

        content = _rows_to_json(list(edited))
        dirty = content.strip() != (raw or "").strip()
        with head_slot:
            section_head(
                "LinkedIn searches",
                "One row per LinkedIn query.",
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

    _render_wwr_categories()
    _render_prompt_editor()


# We Work Remotely is the one feed that narrows server-side. Slugs must match
# WWR_CATEGORY_SLUGS in services/settings.py, which validates the write.
WWR_CATEGORIES = {
    "remote-programming-jobs": "Programming",
    "remote-devops-sysadmin-jobs": "DevOps & sysadmin",
    "remote-design-jobs": "Design",
    "remote-product-jobs": "Product",
    "remote-customer-support-jobs": "Customer support",
    "remote-copywriting-jobs": "Copywriting",
    "remote-sales-and-marketing-jobs": "Sales & marketing",
    "remote-management-and-finance-jobs": "Management & finance",
    "all-other-remote-jobs": "Everything else",
}
WWR_MAX = 5


def _render_wwr_categories():
    """The only other source where you choose what is searched rather than filtering
    afterwards — so it belongs beside the LinkedIn searches, not in Config."""
    values = library.settings()
    if not values:
        return

    current = [
        slug
        for slug in str(values.get("WWR_CATEGORIES") or "").split(",")
        if slug.strip() in WWR_CATEGORIES
    ]

    with st.container(border=True):
        section_head(
            "We Work Remotely categories",
            "Leave empty to read the all-jobs feed.",
            state=f'<span class="mono">{len(current) or "all"} selected</span>',
        )

        picked = st.multiselect(
            "Categories",
            list(WWR_CATEGORIES),
            default=current,
            format_func=lambda slug: WWR_CATEGORIES[slug],
            max_selections=WWR_MAX,
            key="wwr_categories",
            help="Up to five. Picking only relevant categories means fewer wasted jobs.",
        )

        if st.button(
            "Save categories", type="primary", key="wwr_save",
            help="Applies to the next run.",
        ):
            _save_settings({"WWR_CATEGORIES": ",".join(picked)}, "We Work Remotely categories")


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
            help="Instructions the AI uses to pull job titles and skills from your CV.",
        )
        dirty = edited.strip() != current.strip()
        with head_slot:
            section_head(
                "CV keyword extraction prompt",
                "Turns your CV into keywords. Edit the keywords on the CV tab.",
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
        section_head("Export", "Download your jobs as a file.")

        fmt_col, scope_col = st.columns([2, 3], vertical_alignment="bottom")
        with fmt_col:
            fmt = st.segmented_control(
                "Format", ["CSV", "JSON"], default="CSV", key="export_format",
                help="Excludes descriptions and cover letters. Use Backup for everything.",
            ) or "CSV"
        with scope_col:
            scope = st.selectbox(
                "Scope", ["Matched jobs", "All jobs"], key="export_scope",
                help="Matched: at or above your cutoff. All: every scored job.",
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

    with st.container(border=True):
        section_head("Backup", "A snapshot of the whole database.")
        st.markdown(
            '<div class="mono-note">jobs.db<span class="mono-sep">·</span>'
            "safe to take while the stack is running</div>",
            unsafe_allow_html=True,
        )
        st.caption("To restore: stop the stack, replace data/db/jobs.db, start it again.")
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
        f"Deletes **{total:,} jobs** and their status history. "
        "Companies, CV and searches are kept."
    )
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
                help="Deletes every scored job. Queued jobs, companies, searches, CV and settings are kept.",
                icon=":material/delete_forever:", key="clear_all_jobs",
            ):
                _clear_jobs_dialog(total)
        with note_col:
            st.markdown(
                f'<div class="mono-note">{total:,} jobs would be deleted</div>',
                unsafe_allow_html=True,
            )


# ── schedule ────────────────────────────────────────────────────────────────

MODE_LABELS = {"interval": "Every N hours", "daily": "Once a day"}


def _avg_run_minutes(runs: list[dict], sample: int = 5) -> tuple[int, int] | None:
    """Mean wall-clock minutes of the last completed runs, and how many were averaged.

    The count goes in the warning copy: "averaged 47 min" is a claim the user cannot
    weigh without knowing whether it came from five runs or one.
    """
    spans = []
    for run in runs:
        started, finished = run.get("started_at"), run.get("finished_at")
        if not started or not finished:
            continue
        try:
            spans.append(
                (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
            )
        except (ValueError, TypeError):
            continue
        if len(spans) == sample:
            break
    if not spans:
        return None
    return int(sum(spans) / len(spans) / 60), len(spans)


def _time_until(raw: str | None) -> str:
    """'in 4h 12m'. ui.relative_time is past-only — it reads a future timestamp as
    clock skew and answers 'just now', which is the wrong half of the clock here."""
    dt = parse_ts(raw)
    if not dt:
        return ""
    ref = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    seconds = int((dt - ref).total_seconds())
    if seconds <= 0:
        return "due now"
    if seconds < 3600:
        return f"in {max(1, seconds // 60)} min"
    hours, minutes = divmod(seconds // 60, 60)
    if hours < 24:
        return f"in {hours}h {minutes:02d}m"
    return f"in {hours // 24}d {hours % 24}h"


def _parse_clock(raw: str, fallback: clock_time) -> clock_time:
    try:
        hour, _, minute = str(raw).partition(":")
        return clock_time(int(hour), int(minute))
    except (ValueError, TypeError):
        return fallback


def _live_conflict(mode: str, at_time: clock_time, hours: int, minute: int, retention: clock_time) -> str | None:
    """Mirrors services/schedule.py::conflict_message against the widgets as they
    stand. state()["conflict"] describes the SAVED config, so on its own it says
    nothing about the edit in progress."""
    if mode == "daily":
        if (at_time.hour, at_time.minute) == (retention.hour, retention.minute):
            return f"The pipeline and retention would both run at {at_time:%H:%M}."
        return None
    if retention.minute == minute and retention.hour % hours == 0:
        return f"Every {hours}h at :{minute:02d} includes {retention:%H:%M}, when retention runs."
    return None


def _render_schedule():
    """Deliberately outside the workflow fragment: a fragment reruns every two
    seconds, which would fight every widget in here while it is being edited."""
    state = _cached_schedule()
    if not state:
        with st.container(border=True):
            section_head("Schedule", "When the pipeline runs on its own.")
            st.error("The API is unreachable, so the schedule cannot be read.")
        return

    allowed = state.get("allowed_interval_hours") or [1, 2, 3, 4, 6, 8, 12]
    enabled = bool(state.get("enabled"))

    with st.container(border=True):
        section_head(
            "Schedule",
            "When the pipeline runs on its own.",
        )

        next_at = parse_ts(state.get("next_run_at"))
        if enabled and next_at:
            when = f"Next run {next_at:%a %H:%M} · {_time_until(state.get('next_run_at'))}"
        else:
            when = "No scheduled runs"
        st.markdown(
            readout(
                "Runs",
                f'{escape(state.get("description", "—"))} · '
                + status_dot("good" if enabled else "idle", when),
                note=f"Times in {state.get('timezone', 'UTC')}.",
                tip="Timezone is set in .env.",
            ),
            unsafe_allow_html=True,
        )

        new_enabled = st.toggle(
            "Run on a schedule", value=enabled, key="schedule_enabled",
            help="Off: runs only start from Run now.",
        )

        mode = state.get("mode", "daily")
        new_mode = st.radio(
            "How often", list(MODE_LABELS), index=list(MODE_LABELS).index(mode) if mode in MODE_LABELS else 1,
            format_func=lambda m: MODE_LABELS[m], horizontal=True,
            key="schedule_mode", disabled=not new_enabled,
            help="Once a day is gentler on free AI quotas.",
        )

        left, right = st.columns(2)
        if new_mode == "interval":
            with left:
                hours = st.selectbox(
                    "Every", allowed,
                    index=allowed.index(state.get("every_n_hours")) if state.get("every_n_hours") in allowed else 0,
                    format_func=lambda h: f"{h} hours" if h > 1 else "1 hour",
                    key="schedule_hours", disabled=not new_enabled,
                    help="Divisors of 24 only, so gaps stay even across midnight.",
                )
            with right:
                minute = st.number_input(
                    "At minute past the hour", min_value=0, max_value=59,
                    value=int(state.get("at_minute", 0)), step=5,
                    key="schedule_minute", disabled=not new_enabled,
                    help="0 runs on the hour, 30 at half past.",
                )
            payload_times = {"every_n_hours": int(hours), "at_minute": int(minute)}
            interval_minutes = int(hours) * 60
        else:
            with left:
                at = st.time_input(
                    "At", value=_parse_clock(state.get("at_time", "01:00"), clock_time(1, 0)),
                    step=300, key="schedule_at_time", disabled=not new_enabled,
                    help="Start time, in the timezone above.",
                )
            payload_times = {"at_time": f"{at:%H:%M}"}
            interval_minutes = 24 * 60

        with right if new_mode == "daily" else left:
            retention_at = st.time_input(
                "Delete old jobs at", value=_parse_clock(state.get("retention_at_time", "00:00"), clock_time(0, 0)),
                step=300, key="schedule_retention_time",
                help="When the daily clean-up runs. Skipped for the day if a run is active.",
            )

        # The window lives beside the time it runs at rather than in Config: one
        # question, asked once.
        retention_days = st.number_input(
            "Keep jobs for (days)", min_value=1, max_value=3650,
            value=int(library.settings().get("DELETE_OLD_JOBS_DAYS") or 60), step=10,
            key="schedule_retention_days",
            help="Older jobs and runs are deleted. Starred and blocked companies are kept.",
        )

        # The plan on screen, not the saved one: the saved warning would still be
        # showing after the user has already moved the time that caused it.
        conflict = _live_conflict(
            new_mode,
            at if new_mode == "daily" else clock_time(0, 0),
            int(hours) if new_mode == "interval" else 1,
            int(minute) if new_mode == "interval" else 0,
            retention_at,
        )
        if conflict and new_enabled:
            st.warning(
                f"{conflict} One of them will be delayed."
            )

        # A paused newest run holds the schedule, so the next fire will not happen.
        # Decision 25: the strip owes the user both facts, not just the schedule.
        last_run = _health().get("last_run") or {}
        if new_enabled and last_run.get("status") == "paused":
            st.warning(
                "Workflow is paused; scheduled runs are skipped until you resume."
            )

        averaged = _avg_run_minutes(_cached_runs(50))
        if averaged and new_enabled:
            average, sample = averaged
            if average > interval_minutes:
                runs_word = "run" if sample == 1 else "runs"
                st.info(
                    f"Last {sample} {runs_word} averaged {average} min, longer than this "
                    "interval. Overlaps are skipped."
                )

        if st.button("Save schedule", help="Takes effect now. A run in progress is unaffected.", icon=":material/save:", type="primary", key="schedule_save"):
            payload = {
                "enabled": new_enabled,
                "mode": new_mode,
                "retention_at_time": f"{retention_at:%H:%M}",
                **payload_times,
            }
            ok, msg = put_schedule(payload)
            if ok:
                saved, error, _ = put_settings({"DELETE_OLD_JOBS_DAYS": int(retention_days)})
                if saved:
                    _flash("success", "Schedule saved.")
                else:
                    _flash("error", f"Schedule saved, but the retention window was not: {error}")
                _invalidate_settings()
            else:
                _flash("error", f"Could not save the schedule: {msg}")
            st.rerun()


# ── history ─────────────────────────────────────────────────────────────────

STATUS_GLYPH = {
    "success": "✓ Done",
    "failed": "✗ Failed",
    "running": "⟳ Running",
    "paused": "⏸ Paused",
    "stopped": "■ Stopped",
}


def _render_history():
    runs = _cached_runs(50)

    with st.container(border=True):
        section_head("Run history", "Past pipeline runs.")

        if not runs:
            empty_state(
                "📋", "No runs recorded yet",
                "Use <b>Run now</b> on the Workflow tab to start one.",
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

        only_failed = st.toggle(
            "Failed runs only", key="history_failed_only",
            help="Hide successful, paused and stopped runs.",
        )
        shown = [r for r in runs if r.get("status") == "failed"] if only_failed else runs

        chart = [r for r in reversed(runs[:14])]
        if len(chart) > 1:
            st.markdown(
                '<div class="detail-label">Jobs matched per run (last 14)</div>',
                unsafe_allow_html=True,
            )
            st.line_chart(
                {"matched": [r.get("jobs_matched", 0) or 0 for r in chart]},
                height=120, color=BLUE,
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
        st.caption("Click a row for its log.")
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
        f"stage       {run.get('stage') or '—'}",
        f"detail      {run.get('stage_detail') or '—'}",
        f"started_at  {run.get('started_at')}",
        f"finished_at {run.get('finished_at') or '—'}",
        f"scraped     {run.get('jobs_scraped', 0)}",
        f"scored      {run.get('jobs_scored', 0)}",
        f"matched     {run.get('jobs_matched', 0)}",
    ]
    st.code("\n".join(lines), language=None)
    if run.get("error"):
        st.error(run["error"])

    # Stage 6b: Event history drill-down with expandable context
    run_id = run.get("id")
    if run_id:
        events = get_run_events(run_id)
        if events:
            st.markdown('<div class="detail-label">Event log & context</div>', unsafe_allow_html=True)
            for ev in events:
                lvl = ev.get("level", "info")
                badge = "[ERROR]" if lvl == "error" else "[WARN]" if lvl == "warning" else "[INFO]"
                st.markdown(f"**`{badge}` `[{ev.get('stage')}]`** {escape(ev.get('message', ''))}")
                ctx = ev.get("context")
                if ctx:
                    with st.expander(f"Payload context ({ev.get('stage')})"):
                        st.code(ctx, language="json" if ctx.startswith("{") else None)


# ── configuration ───────────────────────────────────────────────────────────
#
# Everything here is stored in app_settings and applies to the next run without a
# restart. .env only seeds these the first time the database is created.

LLM_PRESETS = {
    "Google Gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "OpenAI": "https://api.openai.com/v1/chat/completions",
    "Anthropic": "https://api.anthropic.com/v1/chat/completions",
    "Groq": "https://api.groq.com/openai/v1/chat/completions",
    "OpenRouter": "https://openrouter.ai/api/v1/chat/completions",
    "Together": "https://api.together.xyz/v1/chat/completions",
}
CUSTOM_PRESET = "Custom"

# Read-only because the container is built with them: the scheduler takes the
# timezone at startup and the rest are wiring. Shown rather than hidden, so they
# do not look broken when they refuse to move.
ENV_ONLY = {
    "GENERIC_TIMEZONE": "Timezone for schedules and timestamps.",
    "APP_UID": "Must match your host user id.",
    "API_PORT / DASHBOARD_PORT": "Host ports.",
    "DB_PATH": "Database file path in the container.",
    "API_URL": "Where the dashboard reaches the API.",
}


def _int_setting(values: dict, key: str, default: int) -> int:
    """`values.get(key) or default` would read a stored 0 — valid for both the cutoff
    and the delay — as unset, show the default and write it back on the next Save."""
    try:
        return int(values[key])
    except (KeyError, TypeError, ValueError):
        return default


def _apply_secret(payload: dict, key: str, value: str | None) -> None:
    """The blank-means-unchanged half of _secret_input: None clears the stored value,
    text replaces it, and "" is the untouched field, which must not be sent at all."""
    if value is None or value:
        payload[key] = value


def _save_settings(payload: dict, what: str):
    ok, msg, reclassified = put_settings(payload)
    if ok:
        note = f"{what} saved."
        if reclassified:
            note += f" {reclassified} jobs were re-labelled against the new cutoff."
        _flash("success", note)
        _invalidate_settings()
    else:
        _flash("error", f"Could not save {what.lower()}: {msg}")
    st.rerun()


def _secret_input(label: str, key: str, values: dict, help: str | None = None):
    """A stored secret is never sent back to us, so the field starts empty and a
    blank one means "leave it alone". Clearing has to be explicit."""
    meta = values.get(key) or {}
    stored = bool(meta.get("set"))
    hint = meta.get("hint") or ""

    typed = st.text_input(
        label,
        value="",
        type="password",
        key=f"cfg_{key}",
        # A value too short to hint at comes back with an empty hint rather than
        # its own last characters, so the placeholder has to cope with one.
        placeholder=(f"stored, ends {hint}" if hint else "stored") if stored else "not set",
        help=help,
    )
    clear = False
    if stored:
        clear = st.checkbox(
            f"Clear {label.lower()}", key=f"cfg_clear_{key}",
            help="Removes the stored value on save.",
        )
    if clear:
        return None
    return typed or ""


def _render_providers(values: dict):
    with st.container(border=True):
        section_head(
            "LLM provider",
            "Any OpenAI-compatible provider works.",
        )

        current_url = values.get("LLM_URL") or ""
        preset = next((name for name, url in LLM_PRESETS.items() if url == current_url), CUSTOM_PRESET)
        names = list(LLM_PRESETS) + [CUSTOM_PRESET]
        chosen = st.selectbox(
            "Provider", names, index=names.index(preset), key="cfg_llm_preset",
            help="Scores jobs and writes cover letters. Pick Custom for your own endpoint.",
        )
        if chosen == CUSTOM_PRESET:
            url = st.text_input(
                "Endpoint", value=current_url, key="cfg_llm_url",
                help="Full URL ending in /chat/completions.",
            )
        else:
            # Deliberately unkeyed: Streamlit keeps keyed widget state across reruns
            # and ignores `value`, so a keyed field here would show — and save — the
            # previous provider's endpoint after switching preset.
            url = LLM_PRESETS[chosen]
            st.text_input(
                "Endpoint", value=url, disabled=True,
                help="Set by the provider. Pick Custom to edit.",
            )
        model = st.text_input(
            "Model", value=values.get("LLM_MODEL") or "", key="cfg_llm_model",
            help="As your provider names it, e.g. gemini-2.5-flash.",
        )
        api_key = _secret_input(
            "API key", "LLM_API_KEY", values,
            help="Required for scoring. Get one from your provider; hidden after saving.",
        )

        if st.button(
            "Save provider", icon=":material/save:", type="primary", key="cfg_save_llm",
            help="Applies to the next job scored. Nothing is re-scored.",
        ):
            payload = {"LLM_URL": url.strip(), "LLM_MODEL": model.strip()}
            _apply_secret(payload, "LLM_API_KEY", api_key)
            _save_settings(payload, "Provider")


def _render_scoring(values: dict):
    with st.container(border=True):
        section_head("Scoring", "What counts as a match, and how fast the scorer works.")

        cutoff = st.slider(
            "Match cutoff", 0, 100, value=_int_setting(values, "FILTERING_SCORE", 60),
            key="cfg_cutoff",
            help="Jobs scoring at or above this are Matched. Changing it re-labels existing jobs.",
        )
        delay = st.number_input(
            "Seconds between scored jobs", min_value=0, max_value=3600,
            value=_int_setting(values, "SCORING_DELAY_SECONDS", 20), step=5, key="cfg_delay",
            help="Wait between AI calls, for free-tier rate limits. Sets how long a run takes.",
        )

        if st.button(
            "Save scoring", icon=":material/save:", type="primary", key="cfg_save_scoring",
            help="A new cutoff also re-labels existing jobs.",
        ):
            _save_settings(
                {"FILTERING_SCORE": int(cutoff), "SCORING_DELAY_SECONDS": int(delay)}, "Scoring"
            )


def _render_email(values: dict):
    with st.container(border=True):
        section_head("Email", "The account applications are sent from.")

        configured = bool(values.get("SMTP_USER")) and bool(
            (values.get("SMTP_APP_PASSWORD") or {}).get("set")
        )
        if not configured:
            st.info("SMTP is not set up, so no emails are sent.")

        # Visible, not a tooltip: this is the one switch on the page that mails
        # strangers, and a hover is not a warning to someone flipping it in passing.
        st.warning(
            "Automatic sending emails real employers for matched jobs. Sent mail cannot be recalled.",
            icon=":material/outgoing_mail:",
        )
        auto = st.toggle(
            "Send applications automatically", value=bool(values.get("AUTO_EMAIL")),
            key="cfg_auto_email",
        )
        sender = st.text_input(
            "Sender name", value=values.get("SENDER_NAME") or "", key="cfg_sender",
            help="Your name on application emails and cover letters.",
        )

        left, right = st.columns(2)
        with left:
            host = st.text_input(
                "SMTP host", value=values.get("SMTP_HOST") or "", key="cfg_smtp_host",
                help="Your mail provider's outgoing server, e.g. smtp.gmail.com.",
            )
            user = st.text_input(
                "SMTP user", value=values.get("SMTP_USER") or "", key="cfg_smtp_user",
                help="Mailbox applications are sent from; shown on cover letters.",
            )
        with right:
            port = st.number_input(
                "SMTP port",
                help="587 for most providers, 465 if yours requires SSL.",
                min_value=1, max_value=65535,
                value=int(values.get("SMTP_PORT") or 587), key="cfg_smtp_port",
            )
            password = _secret_input(
                "App password", "SMTP_APP_PASSWORD", values,
                help="An app password from your account's security settings, not your login password.",
            )

        save_col, test_col = st.columns([1, 1])
        with save_col:
            if st.button(
                "Save email", icon=":material/save:", type="primary", key="cfg_save_email",
                help="Applies to the next email sent.",
            ):
                payload = {
                    "AUTO_EMAIL": bool(auto),
                    "SENDER_NAME": sender.strip(),
                    "SMTP_HOST": host.strip(),
                    "SMTP_PORT": int(port),
                    "SMTP_USER": user.strip(),
                }
                _apply_secret(payload, "SMTP_APP_PASSWORD", password)
                _save_settings(payload, "Email")
        with test_col:
            if st.button(
                "Send test email", icon=":material/outgoing_mail:", key="cfg_test_email",
                disabled=not configured,
                help="Sends to your own account, never to an employer.",
            ):
                ok, msg = send_email(
                    values.get("SMTP_USER") or "",
                    "Find Me a Job: test email",
                    "SMTP is configured correctly.",
                )
                _flash("success" if ok else "error", "Test email sent." if ok else f"Test email failed: {msg}")
                st.rerun()


def _render_notifications(values: dict):
    with st.container(border=True):
        section_head(
            "Notifications",
            "Run summaries go to every channel you fill in.",
        )

        telegram_id = st.text_input(
            "Telegram chat id", value=values.get("TELEGRAM_ID") or "", key="cfg_tg_id",
            help="Your Telegram user id; message @get_id_bot to find it.",
        )
        telegram_token = _secret_input(
            "Telegram bot token", "TELEGRAM_BOT_TOKEN", values,
            help="Get it from @BotFather, then send your bot one message.",
        )
        discord = _secret_input(
            "Discord webhook URL", "DISCORD_WEBHOOK_URL", values,
            help="The channel's webhook URL. Keep it private, like a password.",
        )

        save_col, tg_col, dc_col = st.columns([2, 1, 1])
        with save_col:
            if st.button(
                "Save notifications", icon=":material/save:", type="primary", key="cfg_save_notify",
                help="A broken channel is skipped; it never fails a run.",
            ):
                payload: dict = {"TELEGRAM_ID": telegram_id.strip()}
                _apply_secret(payload, "TELEGRAM_BOT_TOKEN", telegram_token)
                _apply_secret(payload, "DISCORD_WEBHOOK_URL", discord)
                _save_settings(payload, "Notifications")
        with tg_col:
            if st.button(
                "Test Telegram", key="cfg_test_tg",
                help="Sends a test message now.",
            ):
                _report_channel_test("telegram")
        with dc_col:
            if st.button(
                "Test Discord", key="cfg_test_dc",
                help="Posts a test message now.",
            ):
                _report_channel_test("discord")


def _report_channel_test(channel: str):
    result = test_notification(channel)
    if result.get("ok"):
        _flash("success", f"{channel.title()} accepted the message (HTTP {result.get('status')}).")
    else:
        _flash("error", f"{channel.title()} failed: {result.get('error')}")
    st.rerun()


def _render_env_only():
    with st.container(border=True):
        section_head(
            "Set in .env, not here",
            "Edit .env and restart the stack to change these.",
        )
        for key, why in ENV_ONLY.items():
            st.markdown(readout(key, escape(why)), unsafe_allow_html=True)


def _render_config():
    values = library.settings()
    if not values:
        with st.container(border=True):
            section_head("Configuration", "")
            st.error("The API is unreachable, so settings cannot be read.")
        return

    # Story 33: the comment above says this to whoever reads the source; the user
    # editing .env and waiting for something to happen needs it on the page.
    st.caption("Saved here; applies to the next run. `.env` is ignored.")

    _render_providers(values)
    _render_scoring(values)
    _render_email(values)
    _render_notifications(values)
    _render_env_only()


# What each source is, in the user's terms rather than the module's. A switch labelled
# "Company boards" tells you nothing about where those jobs come from or what turns them on.
SOURCE_HELP = {
    "companies": "Careers pages from Companies with In workflow on.",
    "linkedin": "Your searches from the Searches tab. Slowest; LinkedIn may rate-limit it.",
    "remoteok": "Remote-jobs feed, up to 100 postings.",
    "himalayas": "Large remote-jobs feed, filtered by your CV keywords.",
    "weworkremotely": "Curated remote-jobs feed.",
}


def _render_sources():
    sources = _cached_sources()
    with st.container(border=True):
        section_head(
            "Sources",
            "Changes apply to the next run.",
        )

        if not sources:
            st.info("No sources are registered.")
            return

        for source in sources:
            enabled = st.toggle(
                source["label"],
                value=bool(source["enabled"]),
                key=f"src_{source['name']}",
                help=SOURCE_HELP.get(source["name"], "Include this source in the next run."),
            )
            if enabled != bool(source["enabled"]):
                if put_source(source["name"], enabled):
                    _invalidate_settings()
                    st.rerun()
                else:
                    _flash("error", f"Could not change {source['label']}.")
                    st.rerun()

        if not any(s["enabled"] for s in sources):
            st.info(
                "All sources off: runs only score what is already queued."
            )

    _render_intake_limits()


def _render_intake_limits():
    """The two numbers that decide how long a run takes.

    They were editable through the API from the day they were added, and invisible here,
    which is the same as not existing: nobody tunes a number they cannot see.
    """
    values = library.settings()
    if not values:
        return

    with st.container(border=True):
        section_head(
            "How much to take in",
            "Each new job costs one AI call, so these set run length.",
        )

        left, right = st.columns(2)
        with left:
            per_run = st.number_input(
                "Jobs per run, in total", min_value=1, max_value=10000,
                value=_int_setting(values, "INTAKE_MAX_PER_RUN", 200), step=25,
                key="cfg_intake_run",
                help="Max new jobs per run, across all sources.",
            )
        with right:
            per_source = st.number_input(
                "Jobs per source", min_value=1, max_value=10000,
                value=_int_setting(values, "INTAKE_MAX_PER_SOURCE", 80), step=10,
                key="cfg_intake_source",
                help="Keeps one big feed from filling the whole run.",
            )

        delay = _int_setting(values, "SCORING_DELAY_SECONDS", 20)
        minutes = round(per_run * delay / 60)
        st.markdown(
            readout(
                "Full-run scoring time",
                f"{per_run} new jobs × {delay}s ≈ <strong>{minutes} min</strong>",
                note="Plus any jobs already queued.",
                tip="Change the delay in Config → Scoring.",
            ),
            unsafe_allow_html=True,
        )

        if st.button("Save limits", icon=":material/save:", type="primary", key="cfg_save_intake",
                     help="Applies to the next run."):
            _save_settings(
                {
                    "INTAKE_MAX_PER_RUN": int(per_run),
                    "INTAKE_MAX_PER_SOURCE": int(per_source),
                },
                "Intake limits",
            )


# ── page ────────────────────────────────────────────────────────────────────


def render_settings_tab():
    with st.container(key="settings_page"):
        page_header(
            "Settings",
            "Run, configure and review your job search.",
        )
        _render_flash()
        _status_strip()

        workflow, config, cv, searches, data, history = st.tabs(
            ["Workflow", "Config", "CV", "Searches", "Data", "History"]
        )
        with workflow:
            _render_workflow()
            _render_schedule()
            _render_sources()
        with config:
            _render_config()
        with cv:
            _render_cv()
        with searches:
            _render_searches()
        with data:
            _render_data()
        with history:
            _render_history()
