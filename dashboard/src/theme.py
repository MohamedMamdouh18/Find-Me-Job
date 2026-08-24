"""Design tokens for the dashboard.

Single source of truth for colour. The categorical slots and the sequential ramp
below are the dataviz reference palette, validated with its own checker against
this app's surfaces (light #fcfcfb, dark #1a1a19):

    categorical adjacent  CVD dE 9.1 light / 8.4 dark   (>= 8 target)
    normal-vision         dE 22.9 light / 19.8 dark     (>= 15 floor)

Two light slots sit below 3:1 on the light surface, so every chart that uses
them ships visible labels and a legend -- colour never carries meaning alone.
"""

import os

# ── surfaces / ink ──────────────────────────────────────────────────────────
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"  # identical in both modes by design
GRIDLINE = "#e1e0d9"
AXIS = "#c3c2b7"

# ── categorical slots (fixed order, never cycled) ───────────────────────────
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MAGENTA = "#e87ba4"
GREEN = "#008300"
VIOLET = "#4a3aa7"
RED = "#e34948"

CATEGORICAL = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]

# ── sequential ramp (single hue, light -> dark) ─────────────────────────────
SEQ = {
    100: "#cde2fb", 150: "#b7d3f6", 200: "#9ec5f4", 250: "#86b6ef",
    300: "#6da7ec", 350: "#5598e7", 400: "#3987e5", 450: "#2a78d6",
    500: "#256abf", 550: "#1c5cab", 600: "#184f95", 650: "#104281",
    700: "#0d366b",
}

# Ordinal steps must stay >= 2:1 against the surface, so start no lighter than 250.
ORDINAL = [SEQ[250], SEQ[300], SEQ[400], SEQ[450], SEQ[500], SEQ[600]]

# Continuous scale for the heatmap: near-zero recedes toward the surface.
SEQUENTIAL_SCALE = [
    [0.00, "#eef2f6"], [0.01, SEQ[150]], [0.25, SEQ[250]],
    [0.50, SEQ[400]], [0.75, SEQ[500]], [1.00, SEQ[650]],
]

# ── status palette (reserved; always paired with an icon or label) ──────────
GOOD = "#0ca30c"
WARNING = "#fab219"
SERIOUS = "#ec835a"
CRITICAL = "#d03b3b"
NEUTRAL = "#898781"

# ── score bands ─────────────────────────────────────────────────────────────
# Two thresholds, and the app has no third opinion about a score anywhere:
#   >= STRONG_SCORE   strong match
#   >= MATCH_CUTOFF   matched  (the scorer writes ai_status="fit" at exactly this
#                               line, so "Matched" and "at or above the cutoff"
#                               are the same set, not two similar ones)
#   below             below your cutoff
STRONG_SCORE = 80
MATCH_CUTOFF = int(os.getenv("FILTERING_SCORE", "60"))

BAND_STRONG = "strong"
BAND_MATCHED = "matched"
BAND_BELOW = "below"

BAND_LABELS = {
    BAND_STRONG: "Strong match",
    BAND_MATCHED: "Matched",
    BAND_BELOW: "Below your cutoff",
}
BAND_COLORS = {
    BAND_STRONG: SEQ[600],
    BAND_MATCHED: SEQ[450],
    # Grey rather than a third blue: below the cutoff is not a weaker shade of
    # matched, it is outside the set the rest of the app counts.
    BAND_BELOW: "#8b8a84",
}


def score_band(score) -> str:
    value = int(score or 0)
    if value >= STRONG_SCORE:
        return BAND_STRONG
    if value >= MATCH_CUTOFF:
        return BAND_MATCHED
    return BAND_BELOW


def score_color(score) -> str:
    """Magnitude, so one hue getting darker — not a red/amber/green rainbow."""
    return BAND_COLORS[score_band(score)]


# ── shared Plotly layout ────────────────────────────────────────────────────
FONT_STACK = 'system-ui, -apple-system, "Segoe UI", sans-serif'
MONO_STACK = '"IBM Plex Mono", ui-monospace, SFMono-Regular, monospace'

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family=FONT_STACK, size=12, color=INK_SECONDARY),
    margin=dict(t=44, b=24, l=16, r=16),
    hoverlabel=dict(
        bgcolor="#ffffff",
        bordercolor=AXIS,
        font=dict(family=FONT_STACK, size=12, color=INK),
    ),
    legend=dict(
        font=dict(size=11, color=INK_SECONDARY),
        bgcolor="rgba(0,0,0,0)",
        orientation="h",
        yanchor="bottom", y=-0.18,
        xanchor="left", x=0,
    ),
)

# Kept separate from CHART_LAYOUT so a chart can pass its own title text without
# colliding with the shared style dict.
TITLE_STYLE = dict(
    font=dict(size=13, color=INK, family=FONT_STACK),
    x=0, xanchor="left", y=0.97, yanchor="top",
)


def chart_title(text: str) -> dict:
    return dict(text=text, **TITLE_STYLE)

# Axes are chrome: recessive, never competing with the marks.
AXIS_HIDDEN = dict(showgrid=False, showticklabels=False, zeroline=False, showline=False)
AXIS_CATEGORY = dict(
    showgrid=False, zeroline=False, showline=False,
    tickfont=dict(size=11, color=INK_SECONDARY),
)


def bar_text_font(size: int = 11) -> dict:
    return dict(size=size, color=INK_SECONDARY, family=MONO_STACK)
