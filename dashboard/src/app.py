import streamlit as st
from streamlit_autorefresh import st_autorefresh

from components.styles import inject_styles
from components.sidebar import render_sidebar
from components.analytics import render_analytics
from components.jobs_tab import render_jobs_tab
from components.companies_tab import render_companies_tab
from components.settings_tab import render_settings_tab

st.set_page_config(
    page_title="Find Me a Job",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_styles()

# The sidebar status block polls on its own; this is the slow backstop that
# picks up rows written by n8n while the tab sat idle.
st_autorefresh(interval=5 * 60 * 1000, key="autorefresh")

PAGE_RENDERERS = {
    "Analytics": render_analytics,
    "Jobs": render_jobs_tab,
    "Companies": render_companies_tab,
    "Settings": render_settings_tab,
}

PAGE_RENDERERS[render_sidebar()]()
