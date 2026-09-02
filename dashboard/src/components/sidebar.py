"""Navigation, and the answer to "is my scraper alive?" on every page.

The status strip used to live only in Settings, which put the health of the
whole pipeline three clicks away from the pages you actually work in. The
condensed version here reads the same `library` object the Settings strip does,
so the two can never disagree.
"""

import io

import segno
import streamlit as st

import library
from api import get_dashboard_public_url
from components.ui import relative_time, status_dot

PAGES = ["Analytics", "Jobs", "Companies", "Settings"]
PAGE_ICONS = {
    "Analytics": "📊",
    "Jobs": "💼",
    "Companies": "🏢",
    "Settings": "⚙️",
}
NAV_KEY = "nav_page"
GOTO_KEY = "nav_goto"

STRIP_TTL = 15


def goto(page: str):
    """Queued rather than assigned: the nav widget already exists by the time a
    page body runs, and Streamlit refuses a write to a live widget's key."""
    st.session_state[GOTO_KEY] = page


def _pipeline_line(hlth: dict) -> tuple[str, str]:
    curr = hlth.get("current_run")
    if curr:
        stage = curr.get("stage", "running")
        return "ok", f"Running · {stage}"
    last = hlth.get("last_run")
    if not last:
        return "idle", "Pipeline ready"
    if last.get("status") == "failed":
        return "fail", "Last run failed"
    return "ok", "Pipeline ready"


@st.fragment(run_every=STRIP_TTL)
def _status_block():
    """Polls on its own so the page body never reruns underneath the cursor."""
    counts = library.stats()
    hlth = library.health()
    tone, text = _pipeline_line(hlth)
    run = hlth["last_run"]
    when = relative_time(run.get("started_at")) if run else "never"

    st.markdown(
        f'<div class="side-status">'
        f'<div class="side-state">{status_dot(tone, text)}</div>'
        f'<div class="side-nums">Queue {counts["queue"]:,}</div>'
        f'<div class="side-nums">Last run {when}</div>'
        f'<div class="side-age">Counts updated {relative_time(counts["fetched_at"])}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False, max_entries=8)
def _qr_png(url: str) -> bytes:
    """Rendered locally — sending the private tunnel URL to a QR web service would leak it."""
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=6, border=2)
    return buf.getvalue()


def _render_public_link():
    with st.expander("🌐  Public link"):
        # Stated before the URL, not after it: this tunnel puts the whole
        # dashboard on the open internet, and the answer to "what does this
        # expose" should never be something the reader has to work out.
        st.markdown(
            "A Cloudflare quick tunnel serves **this entire dashboard** to anyone with "
            "the link — **no password**. That includes your CV download, every scraped "
            "job, your application statuses, your searches, and Settings, which can "
            "delete all jobs.\n\n"
            "Stop it with `docker compose stop cloudflared`. The link changes every "
            "time the tunnel restarts."
        )
        if not st.session_state.get("public_url"):
            if st.button("Get link", width="stretch", key="get_public_url"):
                st.session_state["public_url"] = get_dashboard_public_url()
                st.rerun()
            return

        url = st.session_state["public_url"]
        if not url:
            st.info("No tunnel URL yet. It takes a few seconds after the stack starts.")
            if st.button("Retry", width="stretch", key="retry_public_url"):
                st.session_state.pop("public_url", None)
                st.rerun()
            return

        st.code(url, language=None, wrap_lines=True)
        st.image(_qr_png(url), width="stretch")
        if st.button("Hide", width="stretch", key="hide_public_url"):
            st.session_state.pop("public_url", None)
            st.rerun()


def _label(page: str, counts: dict) -> str:
    number = {"Jobs": counts.get("total"), "Companies": counts.get("companies")}.get(page)
    icon = PAGE_ICONS[page]
    return f"{icon} {page} {number}" if number else f"{icon} {page}"


def render_sidebar() -> str:
    pending = st.session_state.pop(GOTO_KEY, None)
    if pending in PAGES:
        st.session_state[NAV_KEY] = pending

    requested = st.query_params.get("page")
    if NAV_KEY not in st.session_state:
        st.session_state[NAV_KEY] = requested if requested in PAGES else "Jobs"

    counts = library.stats()
    counts = {**counts, "companies": len(library.companies())}

    with st.sidebar:
        st.markdown('<div class="nav-brand">Find Me a Job</div>', unsafe_allow_html=True)
        choice = st.radio(
            "Navigation",
            PAGES,
            key=NAV_KEY,
            label_visibility="collapsed",
            format_func=lambda p: _label(p, counts),
        )
        _status_block()
        if st.button("↻ Refresh data", width="stretch", help="Re-fetch everything now"):
            st.cache_data.clear()
            st.rerun()
        _render_public_link()

    if st.query_params.get("page") != choice:
        st.query_params["page"] = choice
    return choice
