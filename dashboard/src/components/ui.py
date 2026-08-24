"""Presentation helpers shared by the Jobs and Companies pages.

Both pages are assembled from the same four parts — a page header, a summary
line, a row of view chips and a list of rows — so that markup lives here once
rather than being retyped per page.
"""

import re
from datetime import datetime
from html import escape

import streamlit as st

from theme import BAND_LABELS, MATCH_CUTOFF, score_band, score_color


# ── page chrome ─────────────────────────────────────────────────────────────


def page_header(title: str, subtitle: str, actions: int = 0, action_width: float = 1.25):
    """Title block left, `actions` compact slots right.

    Returns the action columns so the caller drops real widgets into them —
    Streamlit widgets cannot live inside emitted HTML.
    """
    def _write_head():
        # Two calls, not one block: Streamlit sizes a column from its element
        # containers, and a single markdown block holding both lines gets
        # clamped to the first line's height once the header row wraps.
        st.markdown(f'<div class="page-title">{escape(title)}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="page-sub">{escape(subtitle)}</div>', unsafe_allow_html=True)

    if not actions:
        with st.container(key="page_head"):
            _write_head()
        return []

    # Keyed so the stylesheet can stop the action buttons from being squeezed
    # into one-letter-per-line columns on a narrow window. Alignment is left at
    # the default: "bottom" makes Streamlit clamp the title column to one line's
    # height, which drops the subtitle behind the buttons once the row wraps.
    with st.container(key="page_head"):
        cols = st.columns([6.0] + [action_width] * actions)
        with cols[0]:
            _write_head()
    return list(cols[1:])


def summary_line(parts: list[tuple], trailing: str = ""):
    """`[(142, "jobs"), (24, "new")]` -> `142 jobs · 24 new`."""
    # Value and label are siblings, not nested: --muted mixes from the element's
    # own currentColor, so a muted wrapper could not host a full-strength number.
    items = [
        f'<span class="sum-item"><span class="sum-val">{escape(str(value))}</span>'
        f'<span class="sum-lab">{escape(label)}</span></span>'
        for value, label in parts
    ]
    if trailing:
        items.append(f'<span class="sum-item sum-quiet">{escape(trailing)}</span>')
    if not items:
        return
    st.markdown(
        '<div class="summary-line">' + '<span class="sum-sep">·</span>'.join(items) + "</div>",
        unsafe_allow_html=True,
    )


def list_toolbar(text: str):
    st.markdown(f'<div class="list-toolbar">{escape(text)}</div>', unsafe_allow_html=True)


# ── time ────────────────────────────────────────────────────────────────────


def parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def relative_time(raw) -> str:
    """'12 min ago'. Rows carry naive local timestamps, so compare in the same frame."""
    dt = parse_ts(raw)
    if not dt:
        return ""
    ref = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    seconds = (ref - dt).total_seconds()
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} min ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = int(hours / 24)
    if days < 7:
        return f"{days}d ago"
    if days < 31:
        return f"{days // 7}w ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def format_date(raw) -> str:
    dt = parse_ts(raw)
    if not dt:
        return ""
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"


# ── inline marks ────────────────────────────────────────────────────────────


def one_line(text: str) -> str:
    """Scraped titles carry hard newlines that would break a single-line row."""
    return " ".join(str(text or "").split())


_ARABIC = re.compile(r"[\u0600-\u06FF]")


def human_location(raw: str) -> str:
    """LinkedIn hands back "القاهرة القاهرة مصر" — the city repeated, no separator.

    Only the two defects that are actually diagnosable get fixed: a word repeated
    back-to-back, and the missing break before the country, which LinkedIn always
    puts last. Anything already punctuated is left exactly as scraped, because
    splitting a multi-word district ("قسم المعادي") would invent a boundary.
    """
    text = one_line(raw)
    if not text or "," in text or "،" in text:
        return text

    words: list[str] = []
    for word in text.split(" "):
        if not words or words[-1].casefold() != word.casefold():
            words.append(word)
    if len(words) < 2:
        return " ".join(words)
    separator = "، " if _ARABIC.search(text) else ", "
    return " ".join(words[:-1]) + separator + words[-1]


# Streamlit renders button labels as markdown, and scraped titles are full of
# characters it would read as formatting ("C++ / Node[js]", "*Senior* Dev").
_MD_SPECIALS = set("\\`*_[]~$|#<>")


def md_escape(text: str) -> str:
    return "".join("\\" + c if c in _MD_SPECIALS else c for c in text)


def score_chip(score, title: str = "") -> str:
    """The score as one band-coloured chip.

    This replaces a number plus a progress bar: at 95 / 90 / 90 / 85 / 80 the bars
    were the same bar, so the pixels were spent to say nothing the digits did not.
    """
    value = max(0, min(100, int(score or 0)))
    band = score_band(value)
    tip = title or BAND_LABELS[band]
    return (
        f'<span class="score-chip band-{band}" title="{escape(tip, quote=True)}">'
        f"{value}</span>"
    )


def score_html(score, caption: str = "match") -> str:
    value = max(0, min(100, int(score or 0)))
    color = score_color(value)
    return (
        f'<div class="score-pill">'
        f'<span class="score-num" style="color:{color}">{value}<span class="pct">%</span></span>'
        f'<span class="score-cap">{escape(caption)}</span>'
        f'<div class="score-track"><div class="score-fill" '
        f'style="width:{value}%;background:{color}"></div></div>'
        f"</div>"
    )


def state_badge(label: str, css_class: str) -> str:
    """Workflow state — a dotted pill. One concept, one treatment."""
    return f'<span class="badge {css_class}">{escape(label)}</span>'


def attr_tag(label: str) -> str:
    """Job attribute — outlined tag, deliberately unlike a state pill."""
    return f'<span class="tag">{escape(label)}</span>'


def star_mark(is_starred: bool) -> str:
    """User preference — a bare glyph, never a pill."""
    return '<span class="star-mark">★</span>' if is_starred else ""


def meta_line(bits: list[str]) -> str:
    clean = [escape(b) for b in bits if b]
    return '<span class="meta-sep">·</span>'.join(clean)


# ── instrument-panel atoms ──────────────────────────────────────────────────

_TONES = {"ok", "warn", "fail", "idle"}


def human_bytes(n) -> str:
    """2685018 -> '2.6 MB'. Machine values get read by humans."""
    try:
        size = float(n)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def status_dot(tone: str, text: str) -> str:
    tone = tone if tone in _TONES else "idle"
    return f'<span class="dot dot-{tone}"></span>{escape(text)}'


def readout(label: str, value_html: str, note: str = "", tip: str = "", link: str = "") -> str:
    """Uppercase label over a monospace value. The atom of the status strip.

    `note` is the line under the value; `tip` is the hover explanation for a
    number that reads like a contradiction on its own ("Queue 53" next to
    "Scored 10"); `link` turns the note into the way to act on it.
    """
    note_body = escape(note)
    if link:
        note_body = f'<a class="readout-link" href="{escape(link, quote=True)}" target="_blank" rel="noopener">{note_body} ↗</a>'
    note_html = f'<div class="readout-note">{note_body}</div>' if note else ""
    title = f' title="{escape(tip, quote=True)}"' if tip else ""
    label_class = "readout-label has-tip" if tip else "readout-label"
    return (
        f'<div class="readout"{title}><div class="{label_class}">{escape(label)}</div>'
        f'<div class="readout-value">{value_html}</div>{note_html}</div>'
    )


def section_head(title: str, subtitle: str = "", state: str = ""):
    """Card header: title, optional one-line purpose, optional right-aligned state."""
    state_html = f'<span class="section-state">{state}</span>' if state else ""
    sub_html = f'<div class="section-sub">{escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="section-head"><span class="section-name">{escape(title)}</span>'
        f"{state_html}</div>{sub_html}",
        unsafe_allow_html=True,
    )


def keyword_tags(words: list[str], limit: int = 3) -> str:
    """The CV skills this posting names. Evidence for the score, never the score."""
    shown = [w for w in words if w][:limit]
    if not shown:
        return ""
    tags = "".join(f'<span class="kw">{escape(w)}</span>' for w in shown)
    extra = len(words) - len(shown)
    if extra > 0:
        tags += f'<span class="kw kw-more">+{extra}</span>'
    return f'<span class="kw-row">{tags}</span>'


def notice(text: str, tone: str = "idle"):
    """What a hidden chart is waiting for. Never a chart with nothing in it."""
    tone = tone if tone in _TONES else "idle"
    st.markdown(
        f'<div class="notice notice-{tone}">{escape(text)}</div>', unsafe_allow_html=True
    )


def cutoff_note() -> str:
    return f"Matched means the AI scored the job at {MATCH_CUTOFF} or above."
