import streamlit as st
import plotly.graph_objects as go

from api import get_stats, get_daily_applied
from components.stats import render_stats
from constants import (
    AI_STATUSES,
    AI_STATUS_LABELS,
    AI_STATUS_COLORS,
    USER_STATUSES,
    USER_STATUS_LABELS,
    USER_STATUS_COLORS,
)

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font_color="#e8e8e8",
    margin=dict(t=40, b=20, l=20, r=20),
    legend=dict(font=dict(size=11)),
)


def render_analytics():
    stats = get_stats()
    render_stats(stats)

    st.markdown('<div class="section-title">Charts</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=[AI_STATUS_LABELS[s] for s in AI_STATUSES],
                    values=[stats.get(s, 0) for s in AI_STATUSES],
                    marker_colors=[AI_STATUS_COLORS[s] for s in AI_STATUSES],
                    hole=0.7,
                )
            ]
        )
        fig.update_layout(title="AI Status Distribution", **CHART_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=[USER_STATUS_LABELS[s] for s in USER_STATUSES],
                    values=[stats.get(s, 0) for s in USER_STATUSES],
                    marker_colors=[USER_STATUS_COLORS[s] for s in USER_STATUSES],
                    hole=0.7,
                )
            ]
        )
        fig.update_layout(title="User Status Distribution", **CHART_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

    daily = get_daily_applied()
    if daily:
        days = [d["day"][5:] for d in daily]  # "MM-DD"
        applied = [d["applied"] for d in daily]

        fig = go.Figure(
            data=[
                go.Bar(
                    x=days,
                    y=applied,
                    marker_color="#4ade80",
                    text=applied,
                    textposition="outside",
                )
            ]
        )
        fig.update_layout(
            title="Applications — Last 7 Days",
            xaxis_title="Day",
            xaxis_type="category",
            yaxis_title="Applied",
            yaxis=dict(dtick=1),
            **CHART_LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
