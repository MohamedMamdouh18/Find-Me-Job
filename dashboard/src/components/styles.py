import streamlit as st

# Surfaces are mixed from currentColor rather than hardcoded, so a card keeps its
# contrast whatever background Streamlit is rendering — the previous stylesheet
# hardcoded dark hexes behind var() fallbacks that never resolved, which is why
# the stat cards came out as black boxes on a light page.
#
# One consequence worth knowing: a token like --muted mixes from the *element's*
# currentColor, so a muted parent cannot host a full-strength child. Where both
# weights appear on one line the markup emits siblings, never nesting.
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
  --ink:            currentColor;
  --surface-raise:  color-mix(in srgb, currentColor 3%, transparent);
  --surface-hover:  color-mix(in srgb, currentColor 7%, transparent);
  --hairline:       color-mix(in srgb, currentColor 12%, transparent);
  --hairline-soft:  color-mix(in srgb, currentColor 8%, transparent);
  --muted:          color-mix(in srgb, currentColor 58%, transparent);
  --faint:          color-mix(in srgb, currentColor 40%, transparent);

  --accent:         #2a78d6;
  --accent-deep:    #1c5cab;
  --star:           #c98a00;
  --good:           #0ca30c;
  --warning:        #fab219;
  --serious:        #ec835a;
  --critical:       #d03b3b;

  --page-max: 1080px;

  --r-sm: 6px;
  --r-md: 10px;
  --r-lg: 14px;
  --ease: cubic-bezier(0.2, 0, 0, 1);
}

html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }

/* Streamlit hangs a -16px bottom margin on every markdown block to cancel the
   trailing <p> margin that real markdown produces. A raw-HTML block has no such
   margin, so the negative one eats 16px of its measured height and whatever
   follows overlaps it. Neutralise it for blocks that contain no markdown tags. */
[data-testid="stMarkdownContainer"]:not(:has(> p, > h1, > h2, > h3, > h4, > h5, > h6,
                                            > ul, > ol, > pre, > table, > blockquote)) {
  margin-bottom: 0 !important;
}

html, body, [class*="css"], .stApp {
  font-family: 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
}

/* One measure for the whole app. The list pages used to run to 1780px while
   Settings sat at 980, which is most of why clicking between them felt like
   moving between two products. */
.block-container { padding: 1.5rem 2.2rem 3rem; max-width: var(--page-max); }

h1, h2, h3, h4 { text-wrap: balance; letter-spacing: -0.011em; }
p, .stCaption, [data-testid="stCaptionContainer"] { text-wrap: pretty; }
/* pretty-wrap balances the last line, which in a thumb-sized box splits "60"
   across two lines — numbers in widget chrome must never wrap */
[data-testid="stSliderThumbValue"] p,
[data-testid="stSliderTickBar"] div { white-space: nowrap; text-wrap: nowrap; }

/* ── page header ────────────────────────────────────────────────────────── */
.page-title {
  font-size: 1.5rem; font-weight: 600; line-height: 1.15;
  letter-spacing: -0.026em;
}
.page-sub { font-size: 0.86rem; color: var(--muted); }
/* the st-key- class lands on the stVerticalBlock itself, so the element and its
   descendants both need the tighter gap */
[class*="st-key-page_head"],
[class*="st-key-page_head"] [data-testid="stVerticalBlock"] { gap: 0.15rem; }

.summary-line {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0 0.45rem;
  font-size: 0.82rem; margin: 0.7rem 0 1.1rem;
  padding-bottom: 0.85rem; border-bottom: 1px solid var(--hairline-soft);
}
.sum-item { display: inline-flex; align-items: baseline; gap: 0.28rem; }
.sum-val { font-weight: 600; font-variant-numeric: tabular-nums; }
.sum-lab { color: var(--muted); }
.sum-sep, .sum-quiet { color: var(--faint); }

.list-toolbar { font-size: 0.78rem; color: var(--muted); padding: 0.35rem 0 0.45rem; }
[class*="st-key-jobs_select_mode"] label p { white-space: nowrap; }

/* ── sidebar ────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] { min-width: 232px; max-width: 232px; }
[data-testid="stSidebar"] > div:first-child { padding-top: 1.1rem; }
[data-testid="stSidebar"] .block-container { padding: 0.9rem 0.75rem; }

.nav-brand {
  font-size: 0.68rem; font-weight: 600; letter-spacing: 0.16em;
  text-transform: uppercase; color: var(--faint);
  padding: 0 0.35rem 0.7rem; margin-bottom: 0.35rem;
  border-bottom: 1px solid var(--hairline-soft);
}

/* Radio group rebuilt as a nav list: no bullets, full-width rows, real hit areas */
[data-testid="stSidebar"] div[role="radiogroup"] { gap: 0.15rem; }
[data-testid="stSidebar"] div[role="radiogroup"] > label {
  width: 100%; min-height: 40px; margin: 0; padding: 0.42rem 0.6rem;
  border-radius: var(--r-sm); cursor: pointer;
  display: flex; align-items: center;
  transition-property: background-color, color;
  transition-duration: 140ms; transition-timing-function: var(--ease);
}
[data-testid="stSidebar"] div[role="radiogroup"] > label:hover { background: var(--surface-hover); }
[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child { display: none; }
[data-testid="stSidebar"] div[role="radiogroup"] > label p {
  font-size: 0.875rem; font-weight: 500; margin: 0;
  white-space: nowrap;
}
[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  box-shadow: inset 2px 0 0 var(--accent);
}
[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p {
  color: var(--accent); font-weight: 600;
}

/* ── stat tiles (analytics) ─────────────────────────────────────────────── */
.stat-card {
  background: var(--surface-raise);
  border: 1px solid var(--hairline-soft);
  border-radius: var(--r-md);
  padding: 0.85rem 0.95rem;
  min-height: 84px;
  display: flex; flex-direction: column; justify-content: center; gap: 0.28rem;
  transition-property: background-color, border-color;
  transition-duration: 160ms; transition-timing-function: var(--ease);
}
.stat-card:hover { background: var(--surface-hover); border-color: var(--hairline); }
.stat-value {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 1.72rem; font-weight: 600; line-height: 1;
  letter-spacing: -0.02em;
}
.stat-value .unit { font-size: 0.92rem; font-weight: 500; color: var(--faint); margin-left: 1px; }
.stat-label {
  font-size: 0.68rem; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--faint); font-weight: 500;
}
.stat-accent  .stat-value { color: var(--accent); }
.stat-good    .stat-value { color: var(--good); }
.stat-warning .stat-value { color: #b07d00; }

.section-title {
  display: flex; align-items: center; gap: 0.6rem;
  font-size: 0.72rem; font-weight: 600; letter-spacing: 0.13em;
  text-transform: uppercase; color: var(--faint);
  margin: 1.6rem 0 0.9rem;
}
.section-title::after { content: ""; flex: 1 1 auto; height: 1px; background: var(--hairline-soft); }
.section-title .count {
  font-family: 'IBM Plex Mono', monospace; text-transform: none;
  letter-spacing: 0; color: var(--muted); font-variant-numeric: tabular-nums;
}

/* ── state language ─────────────────────────────────────────────────────────
   Four kinds of information, four treatments, so they never blur together:
   a metric (score) is a number and a bar, a workflow state is a dotted pill,
   a job attribute is a plain outlined tag, a user preference is a bare glyph. */
.badge {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: 0.68rem; font-weight: 600;
  padding: 0.14rem 0.5rem; border-radius: 999px;
  letter-spacing: 0.01em; border: 1px solid transparent; white-space: nowrap;
}
.badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

.badge-fit        { color: #1b6b3a; background: color-mix(in srgb, #1b6b3a 12%, transparent); border-color: color-mix(in srgb, #1b6b3a 24%, transparent); }
.badge-not_fit    { color: #8a5a52; background: color-mix(in srgb, #8a5a52 12%, transparent); border-color: color-mix(in srgb, #8a5a52 24%, transparent); }
.badge-new        { color: #256abf; background: color-mix(in srgb, #256abf 12%, transparent); border-color: color-mix(in srgb, #256abf 26%, transparent); }
.badge-applied    { color: #1c5cab; background: color-mix(in srgb, #1c5cab 12%, transparent); border-color: color-mix(in srgb, #1c5cab 26%, transparent); }
.badge-email_sent { color: #16736f; background: color-mix(in srgb, #16736f 12%, transparent); border-color: color-mix(in srgb, #16736f 26%, transparent); }
.badge-referral   { color: #4a3aa7; background: color-mix(in srgb, #4a3aa7 12%, transparent); border-color: color-mix(in srgb, #4a3aa7 26%, transparent); }
.badge-assessment { color: #8a6100; background: color-mix(in srgb, #8a6100 13%, transparent); border-color: color-mix(in srgb, #8a6100 26%, transparent); }
.badge-interview  { color: #a4521f; background: color-mix(in srgb, #a4521f 13%, transparent); border-color: color-mix(in srgb, #a4521f 26%, transparent); }
.badge-offer      { color: #0a7d0a; background: color-mix(in srgb, #0a7d0a 13%, transparent); border-color: color-mix(in srgb, #0a7d0a 26%, transparent); }
.badge-rejected   { color: #b6322f; background: color-mix(in srgb, #b6322f 12%, transparent); border-color: color-mix(in srgb, #b6322f 26%, transparent); }
.badge-wont       { color: #6b6a66; background: color-mix(in srgb, #6b6a66 12%, transparent); border-color: color-mix(in srgb, #6b6a66 24%, transparent); }
.badge-easy       { color: #7a4fb5; background: color-mix(in srgb, #7a4fb5 12%, transparent); border-color: color-mix(in srgb, #7a4fb5 26%, transparent); }

.tag {
  display: inline-flex; align-items: center;
  font-size: 0.68rem; font-weight: 500;
  padding: 0.12rem 0.44rem; border-radius: var(--r-sm);
  border: 1px solid var(--hairline); color: var(--muted); white-space: nowrap;
}
.star-mark { color: var(--star); font-size: 0.86rem; white-space: nowrap; }
.block-mark { font-size: 0.85rem; }

/* ── match score ──────────────────────────────────────────────────────────
   One chip, three bands, and the same three bands wherever a score appears.
   The old row spent a number plus a progress bar on this, and the bars for
   95/90/90/85/80 were indistinguishable — pixels spent to say nothing. */
.score-chip {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 38px; height: 30px; padding: 0 0.4rem;
  border-radius: var(--r-sm);
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 0.95rem; font-weight: 600; letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  border: 1px solid transparent; cursor: default;
}
.band-strong  { color: #fff; background: #184f95; border-color: #184f95; }
.band-matched { color: #1c5cab; background: color-mix(in srgb, #2a78d6 13%, transparent);
                border-color: color-mix(in srgb, #2a78d6 30%, transparent); }
.band-below   { color: var(--muted); background: var(--surface-raise); border-color: var(--hairline); }


.score-pill { display: flex; flex-direction: column; align-items: flex-end; gap: 0.16rem; min-width: 92px; }
.score-num {
  font-family: 'IBM Plex Mono', monospace; font-weight: 600;
  font-size: 1.02rem; line-height: 1; letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.score-num .pct { font-size: 0.68em; opacity: 0.7; margin-left: 1px; }
.score-cap { font-size: 0.6rem; text-transform: uppercase; letter-spacing: 0.1em; color: var(--faint); }
.score-track { width: 100%; height: 3px; border-radius: 999px; background: var(--hairline); overflow: hidden; }
.score-fill { height: 100%; border-radius: 999px; }

/* ── job rows ───────────────────────────────────────────────────────────── */
[class*="st-key-jobrow"], [class*="st-key-companyrow"] {
  border-radius: var(--r-md) !important;
  border-color: var(--hairline-soft) !important;
  padding: 0.45rem 0.8rem !important;
  margin-bottom: 0.4rem;
  transition-property: background-color, border-color;
  transition-duration: 140ms; transition-timing-function: var(--ease);
}
[class*="st-key-jobrow"]:hover, [class*="st-key-companyrow"]:hover {
  background: var(--surface-raise);
  border-color: var(--hairline) !important;
}
[class*="st-key-jobrowsel"] {
  border-color: color-mix(in srgb, var(--accent) 45%, transparent) !important;
  background: color-mix(in srgb, var(--accent) 6%, transparent);
  box-shadow: inset 2px 0 0 var(--accent);
}

/* The row title is a real button so the whole line is clickable and focusable,
   but it has to read as a heading rather than as a control. */
[class*="st-key-jobrow"] button[kind="tertiary"] {
  min-height: 0 !important; padding: 0.1rem 0 !important;
  border: none !important; background: transparent !important;
  justify-content: flex-start !important; text-align: left;
}
[class*="st-key-jobrow"] button[kind="tertiary"] > div { justify-content: flex-start !important; }
[class*="st-key-jobrow"] button[kind="tertiary"] p {
  font-size: 0.95rem !important; font-weight: 600 !important;
  line-height: 1.32; letter-spacing: -0.012em;
  white-space: normal !important; text-align: left;
}
[class*="st-key-jobrow"] button[kind="tertiary"]:hover p { color: var(--accent) !important; }

.job-meta {
  display: flex; align-items: center; justify-content: space-between; gap: 0.75rem;
  font-size: 0.85rem; color: var(--muted); line-height: 1.5;
}
.job-meta-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta-sep { margin: 0 0.5rem; color: var(--faint); }

/* Opens the posting straight from the row. A plain anchor, so it costs no widget
   and its position is fixed at the right edge of every row. */
.row-link {
  flex: 0 0 auto;
  display: inline-flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; border-radius: var(--r-sm);
  font-size: 0.95rem; line-height: 1; text-decoration: none;
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 28%, transparent);
  transition-property: background-color, border-color;
  transition-duration: 140ms; transition-timing-function: var(--ease);
}
.row-link:hover {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border-color: var(--accent);
}
.row-link:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.job-side { display: flex; flex-direction: column; align-items: flex-end; gap: 0.34rem; }
.job-marks { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 0.28rem; }

/* ── bulk action bar ────────────────────────────────────────────────────── */
[class*="st-key-bulk_bar"] {
  border-radius: var(--r-md) !important;
  border-color: color-mix(in srgb, var(--accent) 40%, transparent) !important;
  background: color-mix(in srgb, var(--accent) 5%, transparent);
  padding: 0.5rem 0.8rem !important; margin-bottom: 0.6rem;
}
.bulk-count { font-size: 0.85rem; font-weight: 600; padding-bottom: 0.45rem; }

/* ── job detail typography ──────────────────────────────────────────────── */
.detail-title { font-size: 1.1rem; font-weight: 600; line-height: 1.28; letter-spacing: -0.015em; text-wrap: balance; }
.detail-marks { display: flex; flex-wrap: wrap; align-items: center; gap: 0.3rem; margin-bottom: 0.75rem; }
.detail-label {
  font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.11em;
  color: var(--faint); font-weight: 600; margin: 0.65rem 0 0.3rem;
}
.card-rule { height: 1px; background: var(--hairline-soft); margin: 0.85rem 0 0.2rem; }
.history-row {
  display: flex; justify-content: space-between; align-items: baseline; gap: 0.6rem;
  font-size: 0.8rem; padding: 0.3rem 0; border-bottom: 1px solid var(--hairline-soft);
}
.history-row span { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 0.75rem; }

/* ── companies ──────────────────────────────────────────────────────────── */

.company-name { font-size: 0.98rem; font-weight: 600; letter-spacing: -0.013em; display: flex; align-items: center; gap: 0.4rem; }
.company-detail { font-size: 0.82rem; color: var(--muted); margin: 0.18rem 0 0.4rem; line-height: 1.5; text-wrap: pretty; }
.company-detail.is-empty { color: var(--faint); }
.company-foot { display: flex; flex-wrap: wrap; align-items: center; gap: 0.15rem 0.85rem; font-size: 0.76rem; }
.company-added, .company-nolink { color: var(--faint); }
.company-link {
  color: var(--accent); text-decoration: none;
  border-bottom: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
}
.company-link:hover { border-bottom-color: var(--accent); }

/* the row's action menu stays quiet until the row is hovered */
[class*="st-key-companyrow"] [data-testid="stPopover"] { display: flex; justify-content: flex-end; }
[class*="st-key-companyrow"] [data-testid="stPopover"] button {
  min-height: 30px; width: 34px; padding: 0; border-color: transparent;
  color: var(--muted); font-size: 1rem; line-height: 1;
}
[class*="st-key-companyrow"]:hover [data-testid="stPopover"] button { border-color: var(--hairline); }
[class*="st-key-companyrow"] button[data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {
  display: none;
}

/* ── view chips ─────────────────────────────────────────────────────────── */
div[data-testid="stButtonGroup"] button p { font-size: 0.8rem !important; font-weight: 500; }
div[data-testid="stButtonGroup"] button {
  min-height: 36px; border-radius: var(--r-sm);
}

/* ── buttons ────────────────────────────────────────────────────────────── */
div[data-testid="stButton"] button,
div[data-testid="stDownloadButton"] button,
div[data-testid="stLinkButton"] a,
div[data-testid="stPopover"] button {
  font-family: 'IBM Plex Sans', sans-serif;
  font-size: 0.8rem; font-weight: 500;
  border-radius: var(--r-sm); min-height: 38px;
  border: 1px solid var(--hairline);
  transition-property: background-color, border-color, color, transform, box-shadow;
  transition-duration: 140ms; transition-timing-function: var(--ease);
}
div[data-testid="stButton"] button:hover,
div[data-testid="stDownloadButton"] button:hover,
div[data-testid="stLinkButton"] a:hover,
div[data-testid="stPopover"] button:hover {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
div[data-testid="stButton"] button[kind="tertiary"] {
  border-color: transparent !important; background: transparent !important;
  min-height: 30px;
}
div[data-testid="stButton"] button[kind="tertiary"]:hover { background: transparent !important; }

/* A disabled control must look disabled. The primary rule below paints an
   accent background unconditionally, which left "Run now" looking live and
   clickable while sitting under a warning saying it could not work. */
div[data-testid="stButton"] button:disabled,
div[data-testid="stDownloadButton"] button:disabled {
  opacity: 0.55; cursor: not-allowed;
}
div[data-testid="stButton"] button[kind="primary"]:disabled,
div[data-testid="stDownloadButton"] button[kind="primary"]:disabled {
  background: var(--surface-hover) !important;
  border-color: var(--hairline) !important;
  color: var(--muted) !important;
}
div[data-testid="stButton"] button:disabled:hover {
  border-color: var(--hairline) !important; background: var(--surface-hover) !important;
}

div[data-testid="stButton"] button:active,
div[data-testid="stDownloadButton"] button:active { transform: scale(0.975); }
div[data-testid="stButton"] button:focus-visible,
div[data-testid="stDownloadButton"] button:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}

/* Primary is the one affirmative action per view; everything else stays quiet,
   and destructive controls only turn red once they ask for confirmation. */
div[data-testid="stButton"] button[kind="primary"],
div[data-testid="stLinkButton"] a[kind="primary"] {
  background: var(--accent); border-color: var(--accent); color: #fff;
}
div[data-testid="stButton"] button[kind="primary"]:hover,
div[data-testid="stLinkButton"] a[kind="primary"]:hover {
  background: var(--accent-deep); border-color: var(--accent-deep); color: #fff;
}
[class*="st-key-del_"] button:hover, [class*="st-key-bulk_delete"] button:hover {
  border-color: color-mix(in srgb, var(--critical) 55%, transparent);
  background: color-mix(in srgb, var(--critical) 8%, transparent);
  color: var(--critical);
}

/* ── inputs ─────────────────────────────────────────────────────────────── */
div[data-baseweb="select"] > div,
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
  border-radius: var(--r-sm) !important;
  border-color: var(--hairline) !important;
  transition-property: border-color, box-shadow;
  transition-duration: 140ms; transition-timing-function: var(--ease);
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stNumberInput"] input:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent) !important;
}
[data-testid="stWidgetLabel"] p {
  font-size: 0.72rem !important; font-weight: 500;
  letter-spacing: 0.04em; color: var(--muted);
}

/* search is the primary control on both list pages, so it gets real presence */
.st-key-jobs_search div[data-baseweb="input"],
.st-key-companies_search div[data-baseweb="input"] { border-radius: var(--r-md) !important; }
.st-key-jobs_search input,
.st-key-companies_search input { height: 42px; font-size: 0.9rem; }

/* ── expanders / dialogs ────────────────────────────────────────────────── */
div[data-testid="stExpander"] {
  background: transparent;
  border: 1px solid var(--hairline-soft);
  border-radius: var(--r-md);
  overflow: hidden;
}
div[data-testid="stExpander"] summary { font-size: 0.84rem; font-weight: 500; }
div[data-testid="stExpander"] summary:hover { background: var(--surface-raise); }

/* ── empty states ───────────────────────────────────────────────────────── */
.empty-state {
  max-width: 980px;
  border: 1px dashed var(--hairline);
  border-radius: var(--r-lg);
  padding: 2.6rem 1.5rem;
  text-align: center;
  background: var(--surface-raise);
}
.empty-state .glyph { font-size: 1.7rem; opacity: 0.5; display: block; margin-bottom: 0.6rem; }
.empty-state .title { font-size: 0.95rem; font-weight: 600; margin-bottom: 0.3rem; }
.empty-state .hint { font-size: 0.83rem; color: var(--muted); text-wrap: pretty; max-width: 52ch; margin: 0 auto; }
.empty-state .hint code { white-space: nowrap; font-size: 0.78rem; }


/* ── pagination ─────────────────────────────────────────────────────────── */
.pagination-text {
  text-align: center; color: var(--muted);
  font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
}

/* ── settings: instrument panel ─────────────────────────────────────────── */
/* Narrower than the job list on purpose: this page is prose and readouts, and
   full-bleed controls are what made it read as a preferences pane. */


.section-head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 0.6rem; margin-bottom: 0.1rem;
}
.section-name { font-size: 1rem; font-weight: 600; letter-spacing: -0.013em; }
.section-state { font-size: 0.75rem; color: var(--faint); white-space: nowrap; }
.section-sub { font-size: 0.82rem; color: var(--muted); margin-bottom: 0.55rem; }

/* Machine values get the machine face — every mono value here is one. */
.mono, .mono-note, .readout-value, .readout-note {
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace;
  font-variant-numeric: tabular-nums;
}
.mono-note { font-size: 0.78rem; color: var(--muted); line-height: 1.7; }
.mono-sep { color: var(--faint); margin: 0 0.5rem; }

.readout { display: flex; flex-direction: column; gap: 0.18rem; }
.readout-label {
  font-family: 'IBM Plex Sans', sans-serif;
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.11em;
  text-transform: uppercase; color: var(--faint);
}
.readout-value { font-size: 1.05rem; font-weight: 600; letter-spacing: -0.015em; }
.readout-note { font-size: 0.72rem; color: var(--faint); }

.dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 0.45rem; vertical-align: 0.08em;
}
.dot-ok   { background: var(--good); }
.dot-warn { background: #d99a00; }
.dot-fail { background: var(--critical); }
.dot-idle { background: var(--faint); }

[class*="st-key-status_strip"] {
  border-radius: var(--r-md) !important;
  border-color: var(--hairline) !important;
  background: var(--surface-raise);
  padding: 0.7rem 1rem !important;
  margin-bottom: 0.4rem;
}

[class*="st-key-run_failure"], [class*="st-key-danger_zone"] {
  border-radius: var(--r-md) !important;
  border-color: color-mix(in srgb, var(--critical) 40%, transparent) !important;
  background: color-mix(in srgb, var(--critical) 4%, transparent);
  padding: 0.7rem 0.9rem !important;
}
[class*="st-key-danger_zone"] .section-name { color: var(--critical); }
.failure-title { font-size: 0.9rem; font-weight: 600; color: var(--critical); margin-bottom: 0.25rem; }
.failure-body { font-size: 0.82rem; color: var(--muted); margin-bottom: 0.35rem; }

.tag-row { display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0.15rem 0 0.5rem; }
.tag-strong {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
  background: color-mix(in srgb, var(--accent) 7%, transparent);
}
.tag-quiet { color: var(--faint); border-style: dashed; }

/* Tab strip reads as navigation, not as a row of links. The default spacing puts
   adjacent labels a few pixels apart, which is a mis-click waiting to happen. */
[data-baseweb="tab-list"] { gap: 1.1rem; }
button[data-baseweb="tab"] {
  padding: 0.55rem 0.9rem !important;
  min-height: 42px;
  border-radius: var(--r-sm) var(--r-sm) 0 0;
  transition: background-color 140ms var(--ease);
}
button[data-baseweb="tab"] p { font-size: 0.9rem !important; font-weight: 500; }
button[data-baseweb="tab"]:hover { background: var(--surface-hover); }
button[data-baseweb="tab"][aria-selected="true"] p { font-weight: 600; }

/* ── run history rows ───────────────────────────────────────────────────── */
.run-row {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.5rem 0.7rem; border-radius: var(--r-sm);
  border: 1px solid transparent; font-size: 0.82rem;
}
.run-row:hover { background: var(--surface-raise); border-color: var(--hairline-soft); }
.run-when { font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums; color: var(--muted); }
.run-counts { color: var(--muted); font-variant-numeric: tabular-nums; }
.run-error { color: var(--critical); font-size: 0.78rem; padding: 0 0.7rem 0.5rem 2.4rem; }

[data-testid="stMetricValue"], .run-counts, .stat-value { font-variant-numeric: tabular-nums; }
.stPlotlyChart { overflow: hidden; }


/* ── evidence for a score ─────────────────────────────────────────────────
   The row's third line and the dialog's top block. Both answer "why this
   number", which the app previously never answered anywhere. */
.job-evidence {
  display: flex; align-items: center; justify-content: space-between;
  gap: 0.6rem; min-height: 22px; margin-top: 0.1rem;
}
.kw-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.25rem; min-width: 0; }
.kw {
  font-size: 0.7rem; font-weight: 500; white-space: nowrap;
  padding: 0.08rem 0.4rem; border-radius: var(--r-sm);
  color: var(--accent-deep);
  background: color-mix(in srgb, var(--accent) 9%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 22%, transparent);
}
.kw-more { color: var(--faint); background: transparent; border-style: dashed; }
.job-row-marks { display: flex; align-items: center; gap: 0.28rem; flex: 0 0 auto; }

.evidence { display: flex; flex-direction: column; gap: 0.3rem; margin-bottom: 0.2rem; }
.ev-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.28rem; }
.ev-label {
  flex: 0 0 5.5rem; font-size: 0.68rem; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase; color: var(--faint);
}
.ev-none { font-size: 0.8rem; color: var(--muted); }

/* ── active filter chips ─────────────────────────────────────────────────
   A filter you cannot see is a filter you cannot undo. */
[class*="st-key-filter_chips"] {
  align-items: center; gap: 0.3rem; flex-wrap: wrap;
  padding: 0.1rem 0 0.5rem;
}
.chip-lead {
  font-size: 0.7rem; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--faint); padding-right: 0.15rem;
}
[class*="st-key-chip_"] button {
  min-height: 26px !important; padding: 0 0.55rem !important;
  border: 1px solid color-mix(in srgb, var(--accent) 28%, transparent) !important;
  background: color-mix(in srgb, var(--accent) 8%, transparent) !important;
  border-radius: 999px !important;
}
[class*="st-key-chip_"] button p { font-size: 0.72rem !important; color: var(--accent-deep); }
[class*="st-key-chip_"] button:hover {
  border-color: var(--accent) !important;
  background: color-mix(in srgb, var(--accent) 15%, transparent) !important;
}
[class*="st-key-chip_clear_all"] button {
  border-color: transparent !important; background: transparent !important;
}
[class*="st-key-chip_clear_all"] button p { color: var(--muted); text-decoration: underline; }

/* ── thresholds and notices ──────────────────────────────────────────────
   What a chart is waiting for, in place of the chart drawn with nothing in it. */
.notice {
  font-size: 0.82rem; color: var(--muted); line-height: 1.55;
  padding: 0.6rem 0.8rem; border-radius: var(--r-sm);
  background: var(--surface-raise); border: 1px solid var(--hairline-soft);
  border-left: 3px solid var(--faint); text-wrap: pretty;
}
.notice-ok   { border-left-color: var(--good); }
.notice-warn { border-left-color: #d99a00; }
.notice-fail { border-left-color: var(--critical); }
.chart-note {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.76rem;
  color: var(--muted); font-variant-numeric: tabular-nums;
  padding: 0.1rem 0 0.4rem;
}

/* ── needs attention ─────────────────────────────────────────────────────── */
[class*="st-key-attn_"] {
  border-radius: var(--r-md) !important;
  border-color: var(--hairline-soft) !important;
  padding: 0.35rem 0.85rem !important; margin-bottom: 0.35rem;
}
[class*="st-key-attn_"]:hover { background: var(--surface-raise); }
.attn-text { font-size: 0.86rem; line-height: 1.5; text-wrap: pretty; }

/* ── ranked lists (sources, companies) ───────────────────────────────────── */
.rank-list { display: flex; flex-direction: column; }
.rank-row {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 0.6rem; padding: 0.32rem 0; border-bottom: 1px solid var(--hairline-soft);
}
.rank-name {
  font-size: 0.86rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rank-val {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.86rem; font-weight: 600;
  font-variant-numeric: tabular-nums; text-align: right;
}

/* ── compact table rows (companies) ──────────────────────────────────────── */
.list-head {
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.11em;
  text-transform: uppercase; color: var(--faint); padding: 0 0 0.15rem;
}
.cell-num {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.88rem; font-weight: 600;
  font-variant-numeric: tabular-nums; color: var(--ink);
}
.cell-quiet { font-size: 0.78rem; color: var(--muted); font-variant-numeric: tabular-nums; }

/* ── sidebar status ──────────────────────────────────────────────────────── */
.side-status {
  padding: 0.7rem 0.55rem 0.5rem; margin-top: 0.5rem;
  border-top: 1px solid var(--hairline-soft);
  display: flex; flex-direction: column; gap: 0.18rem;
}
.side-state { font-size: 0.79rem; font-weight: 500; }
.side-nums {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
  color: var(--muted); font-variant-numeric: tabular-nums;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.side-age { font-size: 0.68rem; color: var(--faint); }
[data-testid="stSidebar"] div[data-testid="stExpander"] { border: none; margin-top: 0.35rem; }
[data-testid="stSidebar"] div[data-testid="stExpander"] summary { font-size: 0.8rem; }

/* ── unsaved state ───────────────────────────────────────────────────────── */
.unsaved { color: #b07d00; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
.readout-link { color: var(--accent); text-decoration: none; }
.readout-link:hover { text-decoration: underline; }
.readout-label.has-tip { border-bottom: 1px dotted var(--hairline); cursor: help; display: inline-block; }

/* ── job detail panel ─────────────────────────────────────────────────────
   A column beside the list rather than a modal over it: a modal dims the rows
   you are comparing against, and closing it is the only way back to them.
   The panel only exists once a job is picked, so an unopened list keeps the
   full width, and opening one widens the page instead of halving the list. */
.block-container:has(.split-open) { max-width: 1500px; }
.split-open { display: none; }

[class*="st-key-job_detail"] {
  position: sticky; top: 0.75rem;
  max-height: calc(100vh - 1.75rem);
  overflow-y: auto; overscroll-behavior: contain;
  border-radius: var(--r-lg) !important;
  border-color: var(--hairline) !important;
  padding: 0.5rem 1rem 1rem !important;
}
/* Sticky travels inside its containing block, and Streamlit wraps each element
   in a block sized to its own content — so the panel's wrapper was exactly as
   tall as the panel and there was nowhere to travel. Growing the wrapper to fill
   the column gives it the whole list's height to stick through. The column must
   also keep its default stretch: never align-items: flex-start on this row. */
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-job_detail"]) { flex: 1 1 auto; }
[class*="st-key-job_detail"]::-webkit-scrollbar { width: 8px; }
[class*="st-key-job_detail"]::-webkit-scrollbar-thumb {
  background: var(--hairline); border-radius: 999px;
}
/* `help=` wraps the button in shrink-wrapped tooltip spans, so aligning the
   container is not enough — the stack itself has to be pushed across. */
[class*="st-key-close_"] { width: 100% !important; }
[class*="st-key-close_"] > * { margin-left: auto !important; }
[class*="st-key-close_"] button {
  min-height: 28px !important; width: 30px; padding: 0 !important;
  border-color: transparent !important; color: var(--muted);
}
[class*="st-key-close_"] button:hover { color: var(--critical); }

.detail-facts-line { font-size: 0.83rem; color: var(--muted); margin: 0.15rem 0 0.7rem; }
.detail-headline {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
  margin-bottom: 0.85rem;
}
.detail-headline .score-chip { min-width: 46px; height: 34px; font-size: 1.05rem; }
.detail-band { font-size: 0.85rem; font-weight: 600; }
.detail-marks { display: flex; flex-wrap: wrap; align-items: center; gap: 0.3rem; }

/* The posting arrives as one unbroken line; this is what it looks like once the
   bullets are restored. */
.posting { font-size: 0.86rem; line-height: 1.65; color: var(--ink); text-wrap: pretty; }
.posting p { margin: 0 0 0.6rem; }
.posting ul { margin: 0 0 0.7rem; padding-left: 1.15rem; }
.posting li { margin-bottom: 0.28rem; }
mark.kw-hit {
  background: color-mix(in srgb, var(--accent) 18%, transparent);
  color: inherit; padding: 0 0.15rem; border-radius: 3px;
}

/* ── narrow screens ─────────────────────────────────────────────────────── */
/* Below this width the header cannot hold the title and its actions on one
   line without squeezing the buttons to one letter per row, so the title takes
   the full width and the actions drop underneath it. */
@media (max-width: 1150px) {
  [class*="st-key-page_head"] [data-testid="stHorizontalBlock"] {
    flex-wrap: wrap; row-gap: 0.6rem; align-items: flex-start;
  }
  [class*="st-key-page_head"] [data-testid="stHorizontalBlock"] > div { min-width: 150px; flex-grow: 1; }
  [class*="st-key-page_head"] [data-testid="stHorizontalBlock"] > div:first-child { min-width: 100%; }
}

@media (max-width: 900px) {
  .block-container { padding: 1.1rem 1rem 2.5rem; }
  .page-title { font-size: 1.3rem; }
  .job-side { align-items: flex-start; }
  .job-marks { justify-content: flex-start; }
  .score-pill { align-items: flex-start; }
}

@media (prefers-reduced-motion: reduce) {
  * { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}
</style>
"""


def inject_styles():
    st.markdown(_CSS, unsafe_allow_html=True)


def section_title(label: str, count: str = ""):
    count_html = f'<span class="count">{count}</span>' if count else ""
    st.markdown(f'<div class="section-title">{label}{count_html}</div>', unsafe_allow_html=True)


def empty_state(glyph: str, title: str, hint: str):
    st.markdown(
        f"""
        <div class="empty-state">
          <span class="glyph">{glyph}</span>
          <div class="title">{title}</div>
          <div class="hint">{hint}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
