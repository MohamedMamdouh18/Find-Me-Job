from datetime import datetime, timedelta

import plotly.graph_objects as go
import streamlit as st

from api import get_stats, get_daily_applied, get_stats_by_source, get_scores
from components.stats import render_stats
from constants import (
    AI_STATUSES,
    AI_STATUS_LABELS,
    AI_STATUS_COLORS,
    USER_STATUSES,
    USER_STATUS_LABELS,
    USER_STATUS_COLORS,
    HEATMAP_COLORSCALE,
    SOURCE_COLORS,
    CHART_LAYOUT,
)

HEATMAP_DAYS = 365


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_heatmap_data(daily: list[dict]) -> dict:
    """Transform daily-applied list into a GitHub-style calendar heatmap matrix."""
    daily_map = {d["day"]: d["applied"] for d in daily}

    today = datetime.now().date()
    start = today - timedelta(days=HEATMAP_DAYS - 1)
    start = start - timedelta(days=start.weekday())

    weeks: list[datetime] = []
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
    seen_months: set[str] = set()
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


def _score_color(ratio: float) -> str:
    """Red -> Yellow -> Green gradient based on 0-1 ratio."""
    if ratio < 0.5:
        r, g = 255, int(255 * ratio * 2)
    else:
        r, g = int(255 * (1 - ratio) * 2), 255
    return f"rgba({r}, {g}, 90, 0.85)"


# ---------------------------------------------------------------------------
# Individual chart builders
# ---------------------------------------------------------------------------

def _ai_status_donut(stats: dict) -> go.Figure:
    fit = stats.get("fit", 0)
    not_fit = stats.get("not_fit", 0)
    total = fit + not_fit
    fit_pct = round(fit / total * 100) if total else 0

    fig = go.Figure(
        data=[
            go.Pie(
                labels=[AI_STATUS_LABELS[s] for s in AI_STATUSES],
                values=[stats.get(s, 0) for s in AI_STATUSES],
                marker=dict(
                    colors=[AI_STATUS_COLORS[s] for s in AI_STATUSES],
                    line=dict(width=2, color="rgba(0,0,0,0.15)"),
                ),
                hole=0.68,
                pull=[0.03, 0.03],
                textinfo="label+value+percent",
                textposition="outside",
                textfont=dict(size=12),
                hovertemplate="<b>%{label}</b><br>%{value} jobs (%{percent})<extra></extra>",
            )
        ]
    )
    fig.add_annotation(
        text=f"<b>{fit_pct}%</b><br><span style='font-size:11px'>fit rate</span>",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=22),
    )
    fig.update_layout(
        title="AI Status",
        showlegend=False,
        **CHART_LAYOUT,
    )
    return fig


def _user_status_donut(stats: dict) -> go.Figure:
    """Donut chart with outside labels showing count + percentage."""
    values = [stats.get(s, 0) for s in USER_STATUSES]
    total = sum(values)

    labels = [
        f"{USER_STATUS_LABELS[s]}: {stats.get(s, 0)}"
        for s in USER_STATUSES
    ]
    colors = [USER_STATUS_COLORS[s] for s in USER_STATUSES]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                marker=dict(
                    colors=colors,
                    line=dict(width=2, color="rgba(0,0,0,0.15)"),
                ),
                hole=0.62,
                pull=[0.04] * len(values),
                textinfo="label+percent",
                textposition="outside",
                textfont=dict(size=11),
                hovertemplate="<b>%{label}</b><br>%{percent}<extra></extra>",
                sort=False,
            )
        ]
    )
    fig.add_annotation(
        text=f"<b>{total}</b><br><span style='font-size:11px'>total</span>",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=24),
    )
    fig.update_layout(
        title="User Status",
        showlegend=False,
        **CHART_LAYOUT,
    )
    return fig


def _source_bars(source_data: list[dict]) -> go.Figure:
    """Horizontal bar chart showing applied jobs per source."""
    source_data = [s for s in source_data if s.get("applied", 0) > 0]

    if not source_data:
        fig = go.Figure()
        fig.add_annotation(text="No applied jobs data", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(**CHART_LAYOUT)
        return fig

    total_applied = sum(s["applied"] for s in source_data)
    source_data = sorted(source_data, key=lambda s: s["applied"])

    sources = [s["source"] for s in source_data]
    applied = [s["applied"] for s in source_data]
    totals = [s["total"] for s in source_data]
    pcts = [round(a / total_applied * 100, 1) if total_applied else 0 for a in applied]
    colors = [SOURCE_COLORS[i % len(SOURCE_COLORS)] for i in range(len(source_data))]

    fig = go.Figure(
        data=[
            go.Bar(
                y=sources,
                x=applied,
                orientation="h",
                marker=dict(
                    color=colors,
                    line=dict(width=1, color="rgba(0,0,0,0.15)"),
                ),
                text=[f"{a}  ({p}%)" for a, p in zip(applied, pcts)],
                textposition="outside",
                textfont=dict(size=12, family="IBM Plex Mono, monospace"),
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Applied: %{x}<br>"
                    "Total jobs: %{customdata}<extra></extra>"
                ),
                customdata=totals,
            )
        ]
    )
    fig.update_layout(
        title="Applied Jobs by Source",
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        **{**CHART_LAYOUT, "margin": dict(t=40, b=20, l=120, r=80)},
    )
    return fig


def _score_histogram(scores: list[int]) -> go.Figure:
    """Gradient-colored histogram of AI scores."""
    if not scores:
        fig = go.Figure()
        fig.add_annotation(text="No score data", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(**CHART_LAYOUT)
        return fig

    bin_size = 10
    bins = []
    for b_start in range(0, 100, bin_size):
        count = sum(1 for s in scores if b_start <= s < b_start + bin_size)
        bins.append({"start": b_start, "count": count})

    labels = [f"{b['start']}-{b['start'] + bin_size - 1}" for b in bins]
    counts = [b["count"] for b in bins]
    total = sum(counts)
    pcts = [round(c / total * 100, 1) if total else 0 for c in counts]
    colors = [_score_color(b["start"] / 90) for b in bins]

    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=counts,
                marker=dict(
                    color=colors,
                    line=dict(width=1, color="rgba(0,0,0,0.15)"),
                ),
                text=[str(c) if c > 0 else "" for c in counts],
                textposition="outside",
                textfont=dict(size=11, family="IBM Plex Mono, monospace"),
                hovertemplate=(
                    "Score %{x}<br>"
                    "<b>%{y}</b> jobs (%{customdata}%)<extra></extra>"
                ),
                customdata=pcts,
            )
        ]
    )
    fig.update_layout(
        title="Score Distribution",
        xaxis=dict(title="Score Range", type="category"),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        bargap=0.08,
        **{**CHART_LAYOUT, "margin": dict(t=40, b=50, l=20, r=20)},
    )
    return fig


def _yearly_heatmap(daily: list[dict]) -> go.Figure:
    """GitHub-style calendar heatmap for application activity."""
    data = _build_heatmap_data(daily)

    max_val = max(
        (v for row in data["z"] for v in row if v is not None),
        default=1,
    )

    fig = go.Figure(
        data=[
            go.Heatmap(
                z=data["z"],
                x=list(range(len(data["z"][0]))),
                y=data["day_labels"],
                hovertext=data["hover"],
                hoverinfo="text",
                colorscale=HEATMAP_COLORSCALE,
                zmin=0,
                zmax=max(max_val, 1),
                showscale=True,
                colorbar=dict(
                    title=dict(text="Apps", side="right"),
                    thickness=10,
                    len=0.6,
                    tickfont=dict(size=10),
                ),
                xgap=3,
                ygap=3,
            )
        ]
    )
    fig.update_layout(
        title="Application Activity — Past Year",
        xaxis=dict(
            tickmode="array",
            tickvals=data["month_ticks"],
            ticktext=data["month_labels"],
            showgrid=False,
            side="top",
        ),
        yaxis=dict(
            showgrid=False,
            autorange="reversed",
            dtick=1,
        ),
        **{**CHART_LAYOUT, "margin": dict(t=60, b=10, l=50, r=20)},
        height=220,
    )
    return fig


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_analytics():
    stats = get_stats()
    render_stats(stats)

    st.markdown('<div class="section-title">Charts</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(_ai_status_donut(stats), use_container_width=True)
    with col2:
        st.plotly_chart(_user_status_donut(stats), use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        source_data = get_stats_by_source()
        if source_data:
            st.plotly_chart(_source_bars(source_data), use_container_width=True)
    with col4:
        scores = get_scores()
        if scores:
            st.plotly_chart(_score_histogram(scores), use_container_width=True)

    daily = get_daily_applied(days=HEATMAP_DAYS)
    if daily:
        st.plotly_chart(_yearly_heatmap(daily), use_container_width=True)
