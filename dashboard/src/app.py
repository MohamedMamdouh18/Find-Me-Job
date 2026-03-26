import streamlit as st
from streamlit_autorefresh import st_autorefresh

from components.styles import inject_styles
from components.analytics import render_analytics
from components.jobs_tab import render_jobs_tab

st.set_page_config(
    page_title="Find Me a Job",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_styles()

st_autorefresh(interval=5 * 60 * 1000, key="autorefresh")

with st.sidebar:
    st.markdown("## 🎯 Find Me a Job")
    tab = st.radio("Navigation", ["Analytics", "Jobs"], label_visibility="collapsed")
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

if tab == "Analytics":
    render_analytics()
else:
    render_jobs_tab()
