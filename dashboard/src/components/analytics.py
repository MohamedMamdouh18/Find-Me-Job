"""Analytics.

The full chart set, with two things kept from the rebuild: the page opens with
the conditions that are true right now and have somewhere to go, and the score
distribution carries your cutoff and your median as rules on the axis — the two
marks that turn a histogram into an argument for moving the cutoff.
"""

from datetime import datetime, timedelta

import plotly.graph_objects as go
import streamlit as st

import library
from components.jobs_filters import VIEW_ALL, VIEW_MATCHED, VIEW_STRONG, apply_preset
from components.sidebar import goto
from components.stats import render_stats
from components.styles import section_title
from components.ui import page_header, status_dot
from constants import (
    AI_STATUSES,
    AI_STATUS_COLORS,
    AI_STATUS_LABELS,
    CHART_LAYOUT,
    HEATMAP_COLORSCALE,
    MATCH_CUTOFF,
    SOURCE_COLORS,
    STRONG_SCORE,
    USER_STATUSES,
    USER_STATUS_COLORS,
    USER_STATUS_LABELS,
)
from theme import (
    AXIS_CATEGORY,
    AXIS_HIDDEN,
    INK,
    INK_MUTED,
    SEQ,
    bar_text_font,
    chart_title,
    score_color,
)

HEATMAP_DAYS = 365
PLOT_CONFIG = {"displayModeBar": False, "responsive": True}
SURFACE = "#fcfcfb"


def clear_analytics_cache():
    library.refresh()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_data(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=msg, x=0.5, y=0.5, showarrow=False, font=dict(size=12, color=INK_MUTED)
    )
    fig.update_layout(height=220, xaxis=AXIS_HIDDEN, yaxis=AXIS_HIDDEN, **CHART_LAYOUT)
    return fig


def _build_heatmap_data(daily: list[dict]) -> dict:
    """Transform daily-applied list into a calendar heatmap matrix."""
    daily_map = {d["day"]: d["applied"] for d in daily}

    # Anchor on the API's last day so the calendar follows GENERIC_TIMEZONE
    # rather than whatever timezone the dashboard container happens to run in.
    today = (
        datetime.strptime(daily[-1]["day"], "%Y-%m-%d").date()
        if daily
        else datetime.now().date()
    )
    start = today - timedelta(days=HEATMAP_DAYS - 1)
    start = start - timedelta(days=start.weekday())

    weeks: list = []
    current = start
    while current <= today:
        weeks.append(current)
        current += timedelta(days=7)

    num_weeks = len(weeks)
    z = [[None] * num_weeks for _ in range(7)]
    hover = [[""] * num_weeks for _ in range(7)]

    for wi, week_start in enumerate(weeks):
        for di in range(7):
            day = week_start + timedelta(days=di)
            if day < start or day > today:
                continue
            day_str = day.strftime("%Y-%m-%d")
            count = daily_map.get(day_str, 0)
            z[di][wi] = count
            hover[di][wi] = (
                f"{day.strftime('%a, %b %d %Y')}<br>"
                f"<b>{count}</b> application{'s' if count != 1 else ''}"
            )

    month_ticks, month_labels = [], []
    seen_months: set = set()
    for wi, week_start in enumerate(weeks):
        for di in range(7):
            day = week_start + timedelta(days=di)
            key = day.strftime("%Y-%m")
            if day.day <= 7 and key not in seen_months:
                seen_months.add(key)
                month_ticks.append(wi)
                month_labels.append(day.strftime("%b"))
                break

    return {
        "z": z,
        "hover": hover,
        "day_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "month_ticks": month_ticks,
        "month_labels": month_labels,
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def _match_rate_donut(stats: dict) -> go.Figure:
    """Part-to-whole over two categories with a headline rate — a donut earns its place."""
    fit = stats.get("fit", 0)
    not_fit = stats.get("not_fit", 0)
    total = fit + not_fit
    fit_pct = round(fit / total * 100) if total else 0

    if not total:
        return _no_data("No scored jobs yet")

    fig = go.Figure(
        data=[
            go.Pie(
                labels=[AI_STATUS_LABELS[s] for s in AI_STATUSES],
                values=[stats.get(s, 0) for s in AI_STATUSES],
                marker=dict(
                    colors=[AI_STATUS_COLORS[s] for s in AI_STATUSES],
                    line=dict(width=2, color=SURFACE),  # 2px surface gap
                ),
                hole=0.74,
                sort=False,
                direction="clockwise",
                textinfo="none",
                hovertemplate="<b>%{label}</b><br>%{value} jobs · %{percent}<extra></extra>",
            )
        ]
    )
    fig.add_annotation(
        text=f"<b>{fit_pct}%</b>", x=0.5, y=0.56, showarrow=False,
        font=dict(size=34, color=INK),
    )
    fig.add_annotation(
        text="match rate", x=0.5, y=0.37, showarrow=False,
        font=dict(size=11, color=INK_MUTED),
    )
    fig.update_layout(
        title=chart_title("Match rate"),
        showlegend=True,
        height=300,
        **{**CHART_LAYOUT, "margin": dict(t=44, b=54, l=16, r=16)},
    )
    return fig


def _score_histogram(bins: list[dict], median: int) -> go.Figure:
    """Score is magnitude, so one hue getting darker — not a red/amber/green rainbow.

    The two vertical rules are the point of the chart: they show how much of the
    distribution sits just under the cutoff, which is the case for lowering it.
    """
    if not bins or not any(b.get("count", 0) for b in bins):
        return _no_data("No scored jobs yet")

    labels = [f"{b['start']}–{b['end']}" for b in bins]
    counts = [b["count"] for b in bins]
    colors = [score_color(b["start"]) for b in bins]

    fig = go.Figure(
        data=[
            go.Bar(
                x=labels, y=counts,
                marker=dict(color=colors, cornerradius=4),
                text=[str(c) if c else "" for c in counts],
                textposition="outside",
                textfont=bar_text_font(10),
                cliponaxis=False,
                hovertemplate="Score %{x}<br><b>%{y}</b> jobs<extra></extra>",
            )
        ]
    )
    peak = max(counts) or 1
    # Bins are categories, so a rule sits on the boundary between two of them:
    # a cutoff of 60 belongs between the 50–59 and 60–69 bars.
    cutoff_x = MATCH_CUTOFF / 10 - 0.5
    fig.add_shape(
        type="line", x0=cutoff_x, x1=cutoff_x, y0=0, y1=peak * 1.30,
        line=dict(color=INK_MUTED, width=1.5, dash="dot"),
    )
    fig.add_annotation(
        x=cutoff_x, y=peak * 1.36, text=f"cutoff {MATCH_CUTOFF}", showarrow=False,
        font=dict(size=10, color=INK_MUTED), xanchor="center",
    )
    if median:
        median_x = median / 10 - 0.5
        # A row lower than the cutoff label: the two rules sit within one bin of
        # each other whenever the median is near the cutoff, and side by side the
        # labels collide into "cutoff 6median 68".
        fig.add_shape(
            type="line", x0=median_x, x1=median_x, y0=0, y1=peak * 1.12,
            line=dict(color=SEQ[600], width=1.5),
        )
        fig.add_annotation(
            x=median_x, y=peak * 1.18, text=f"median {median}", showarrow=False,
            font=dict(size=10, color=SEQ[600]), xanchor="center",
        )

    fig.update_layout(
        title=chart_title("Score distribution"),
        xaxis=dict(type="category", **AXIS_CATEGORY),
        yaxis=dict(**AXIS_HIDDEN, range=[0, peak * 1.48]),
        bargap=0.34,
        height=320,
        showlegend=False,
        **{**CHART_LAYOUT, "margin": dict(t=44, b=40, l=16, r=16)},
    )
    return fig


def _conversion_funnel(funnel: dict) -> go.Figure:
    """Stage-to-stage conversion.

    Counted as *ever reached*, from the status log — a funnel counts arrivals, so
    moving a job on to Interview must not shrink the Applied bar behind it.
    """
    stages = [
        ("Matched", funnel["matched"]),
        ("Applied", funnel["applied"]),
        ("Interviewing", funnel["interviewing"]),
        ("Offers", funnel["offers"]),
    ]
    if not funnel["matched"]:
        return _no_data("Nothing scored yet")

    labels = [s[0] for s in stages]
    values = [s[1] for s in stages]
    ramp = [SEQ[250], SEQ[400], SEQ[550], SEQ[650]]

    # conversion from the previous stage, spelled out rather than left to the eye
    text = []
    for i, v in enumerate(values):
        if i == 0:
            text.append(f"{v}")
        else:
            prev = values[i - 1]
            pct = round(v / prev * 100) if prev else 0
            text.append(f"{v}   ({pct}% of {labels[i - 1].lower()})")

    fig = go.Figure(
        data=[
            go.Bar(
                y=labels[::-1], x=values[::-1], orientation="h",
                marker=dict(color=ramp[::-1], cornerradius=4),
                width=0.5,
                text=text[::-1],
                textposition="outside",
                textfont=bar_text_font(),
                cliponaxis=False,
                hovertemplate="<b>%{y}</b><br>%{x} jobs<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=chart_title("Conversion funnel"),
        xaxis=dict(**AXIS_HIDDEN, range=[0, max(max(values), 1) * 1.5]),
        yaxis=AXIS_CATEGORY,
        height=280,
        showlegend=False,
        **{**CHART_LAYOUT, "margin": dict(t=44, b=16, l=104, r=52)},
    )
    return fig


def _status_breakdown_bar(stats: dict) -> go.Figure:
    """Nine categories with magnitudes is a bar chart.

    This replaced a donut whose eight slices carried unreadable 2.08%-style labels.
    """
    entries = [
        (USER_STATUS_LABELS[s], stats.get(s, 0), USER_STATUS_COLORS[s])
        for s in USER_STATUSES
        if stats.get(s, 0) > 0
    ]
    if not entries:
        return _no_data("No status data yet")

    entries.reverse()
    labels = [e[0] for e in entries]
    values = [e[1] for e in entries]
    colors = [e[2] for e in entries]

    fig = go.Figure(
        data=[
            go.Bar(
                y=labels, x=values, orientation="h",
                marker=dict(color=colors, cornerradius=4),
                width=0.55,
                text=[str(v) for v in values],
                textposition="outside",
                textfont=bar_text_font(),
                cliponaxis=False,
                hovertemplate="<b>%{y}</b><br>%{x} jobs<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=chart_title("Where your jobs stand"),
        xaxis=dict(**AXIS_HIDDEN, range=[0, max(values) * 1.18]),
        yaxis=AXIS_CATEGORY,
        bargap=0.42,
        height=max(300, 30 * len(labels) + 96),
        showlegend=False,
        **{**CHART_LAYOUT, "margin": dict(t=44, b=16, l=100, r=44)},
    )
    return fig


def _source_bars(source_data: list[dict]) -> go.Figure:
    """Which board actually produces applications."""
    source_data = [d for d in source_data if d.get("applied", 0) > 0]
    if not source_data:
        return _no_data("No applications recorded yet")

    source_data = sorted(source_data, key=lambda d: d["applied"])
    sources = [d["source"] for d in source_data]
    applied = [d["applied"] for d in source_data]
    totals = [d["total"] for d in source_data]
    colors = [SOURCE_COLORS[i % len(SOURCE_COLORS)] for i in range(len(source_data))]

    fig = go.Figure(
        data=[
            go.Bar(
                y=sources, x=applied, orientation="h",
                marker=dict(color=colors, cornerradius=4),
                width=0.42,  # category units — keeps two-source charts from turning into slabs
                text=[f"{a} of {t}" for a, t in zip(applied, totals)],
                textposition="outside",
                textfont=bar_text_font(),
                cliponaxis=False,
                customdata=totals,
                hovertemplate=(
                    "<b>%{y}</b><br>Applied: %{x}<br>Scraped: %{customdata}<extra></extra>"
                ),
            )
        ]
    )
    fig.update_layout(
        title=chart_title("Applications by source"),
        xaxis=dict(**AXIS_HIDDEN, range=[0, max(applied) * 1.4]),
        yaxis=AXIS_CATEGORY,
        height=max(190, 34 * len(sources) + 108),
        showlegend=False,
        **{**CHART_LAYOUT, "margin": dict(t=44, b=16, l=92, r=76)},
    )
    return fig


def _top_companies_bar(companies: list[dict], limit: int = 12) -> go.Figure:
    """Ranked magnitude reads as bars; the treemap it replaces clipped its own labels.

    Sorted by best score first: at one job per company a frequency ranking has
    nothing to rank, but the best score always separates them.
    """
    if not companies:
        return _no_data("No company data yet")

    rows = sorted(
        companies, key=lambda c: (c.get("best_score") or 0, c["job_count"]), reverse=True
    )[:limit]
    rows.reverse()
    names = [c["company"] for c in rows]
    scores = [c.get("best_score") or 0 for c in rows]
    counts = [c["job_count"] for c in rows]
    colors = [score_color(s) for s in scores]

    fig = go.Figure(
        data=[
            go.Bar(
                y=names, x=scores, orientation="h",
                marker=dict(color=colors, cornerradius=4),
                text=[
                    f"{s}   ({c} job{'s' if c != 1 else ''})" for s, c in zip(scores, counts)
                ],
                textposition="outside",
                textfont=bar_text_font(),
                cliponaxis=False,
                customdata=counts,
                hovertemplate=(
                    "<b>%{y}</b><br>Best score: %{x}<br>Jobs seen: %{customdata}<extra></extra>"
                ),
            )
        ]
    )
    fig.update_layout(
        title=chart_title(f"Companies by best score (top {len(rows)})"),
        xaxis=dict(**AXIS_HIDDEN, range=[0, 100 * 1.28]),
        yaxis=AXIS_CATEGORY,
        bargap=0.42,
        height=max(300, 26 * len(names) + 100),
        showlegend=False,
        **{**CHART_LAYOUT, "margin": dict(t=44, b=16, l=124, r=76)},
    )
    return fig


def _yearly_heatmap(daily: list[dict]) -> go.Figure:
    """Calendar of application activity — one hue, near-zero receding to the surface."""
    data = _build_heatmap_data(daily)
    max_val = max((v for row in data["z"] for v in row if v is not None), default=1)

    fig = go.Figure(
        data=[
            go.Heatmap(
                z=data["z"],
                x=list(range(len(data["z"][0]))),
                y=data["day_labels"],
                hovertext=data["hover"],
                hoverinfo="text",
                colorscale=HEATMAP_COLORSCALE,
                zmin=0, zmax=max(max_val, 1),
                showscale=True,
                colorbar=dict(
                    thickness=8, len=0.7, outlinewidth=0,
                    tickfont=dict(size=10, color=INK_MUTED),
                ),
                xgap=3, ygap=3,
            )
        ]
    )
    fig.update_layout(
        title=chart_title("Application activity — past year"),
        xaxis=dict(
            tickmode="array",
            tickvals=data["month_ticks"], ticktext=data["month_labels"],
            showgrid=False, zeroline=False, showline=False, side="top",
            tickfont=dict(size=10, color=INK_MUTED),
        ),
        yaxis=dict(
            showgrid=False, zeroline=False, showline=False,
            autorange="reversed", dtick=1,
            tickfont=dict(size=10, color=INK_MUTED),
        ),
        height=216,
        **{**CHART_LAYOUT, "margin": dict(t=58, b=8, l=42, r=16)},
    )
    return fig


# ---------------------------------------------------------------------------
# Needs attention
# ---------------------------------------------------------------------------


def _render_attention(counts: dict, hlth: dict):
    items = library.attention(counts, hlth)
    if not items:
        return
    section_title("Needs attention", f"{len(items)}")
    for index, item in enumerate(items):
        with st.container(border=True, key=f"attn_{index}"):
            text_col, action_col = st.columns([6, 1.5], vertical_alignment="center")
            with text_col:
                st.markdown(
                    f'<div class="attn-text">{status_dot(item["tone"], item["text"])}</div>',
                    unsafe_allow_html=True,
                )
            with action_col:
                if st.button(item["action"], key=f"attn_go_{index}", width="stretch"):
                    _act(item)


def _act(item: dict):
    view = item.get("view")
    if view == "Strong":
        apply_preset(VIEW_STRONG)
    elif view == "Below cutoff":
        apply_preset(VIEW_ALL, score_range=(0, MATCH_CUTOFF - 1))
    elif view == "Matched":
        apply_preset(VIEW_MATCHED)
    goto(item["page"])
    st.rerun()


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------


def render_analytics():
    page_header("Analytics", "How your search is going, from first match to offer.")

    counts = library.stats()
    hlth = library.health()
    funnel = library.funnel()
    counts = {**counts, "applied_ever": funnel["applied"]}

    render_stats(counts)
    _render_attention(counts, hlth)

    # Every chart carries an explicit key: with an empty database several of them
    # render the identical "no data" figure, which would otherwise collide on
    # Streamlit's auto-generated element id.
    section_title("Match quality")
    c1, c2 = st.columns([1, 1.25])
    with c1:
        st.plotly_chart(
            _match_rate_donut(counts), width="stretch", config=PLOT_CONFIG, key="chart_match_rate"
        )
    with c2:
        st.plotly_chart(
            _score_histogram(counts["bins"], counts["median_score"]),
            width="stretch", config=PLOT_CONFIG, key="chart_score_dist",
        )
    st.markdown(
        f'<div class="chart-note">Median {counts["median_score"]}'
        f'<span class="mono-sep">·</span>{counts["strong"]} at or above {STRONG_SCORE}'
        f'<span class="mono-sep">·</span>{counts["below_cutoff"]} below your cutoff of '
        f"{MATCH_CUTOFF}</div>",
        unsafe_allow_html=True,
    )

    section_title("Your pipeline")
    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(
            _conversion_funnel(funnel), width="stretch", config=PLOT_CONFIG, key="chart_funnel"
        )
    with c4:
        st.plotly_chart(
            _status_breakdown_bar(counts), width="stretch", config=PLOT_CONFIG, key="chart_status"
        )

    section_title("Where jobs come from")
    c5, c6 = st.columns([1, 1.15])
    with c5:
        st.plotly_chart(
            _source_bars(library.sources()),
            width="stretch", config=PLOT_CONFIG, key="chart_sources",
        )
    with c6:
        st.plotly_chart(
            _top_companies_bar(list(library.company_stats().values())),
            width="stretch", config=PLOT_CONFIG, key="chart_companies",
        )

    section_title("Activity")
    st.plotly_chart(
        _yearly_heatmap(library.daily_applied(HEATMAP_DAYS)),
        width="stretch", config=PLOT_CONFIG, key="chart_activity",
    )
