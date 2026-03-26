from components.jobs_filters import render_jobs_filters
from components.jobs_table import render_jobs_table


def render_jobs_tab():
    filters = render_jobs_filters()
    render_jobs_table(filters)
