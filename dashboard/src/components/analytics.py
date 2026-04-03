import streamlit as st
import plotly.graph_objects as go

from api import get_stats, get_daily_applied
from components.stats import render_stats

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
                    labels=["Fit", "Not Fit"],
                    values=[stats.get("fit", 0), stats.get("not_fit", 0)],
                    marker_colors=["#4ade80", "#f87171"],
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
                    labels=["New", "Applied", "Won't Apply", "Email Sent"],
                    values=[
                        stats.get("new", 0),
                        stats.get("applied", 0),
                        stats.get("wont_apply", 0),
                        stats.get("email_sent", 0),
                    ],
                    marker_colors=["#60a5fa", "#4ade80", "#fb923c", "#22d3ee"],
                    hole=0.7,
                )
            ]
        )
        fig.update_layout(title="User Status Distribution", **CHART_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

    daily = get_daily_applied()
    if daily:
        # Show short day labels like "Mon 24"
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
