"""First-run checklist and the always-available guide.

A new user lands on a list of jobs that is empty and has no idea the app needs an
AI key, a CV and a first run before anything appears. The checklist says exactly
that, in order, and disappears once it is done; the guide stays in the sidebar with
the setup steps, how a run works, which careers links can be read, and where every
setting lives.
"""

import json

import streamlit as st

import library
from api import get_cv_info, get_param
from components.sidebar import goto

HIDE_KEY = "getting_started_hidden"


@st.cache_data(ttl=30, show_spinner=False)
def _cv_exists() -> bool:
    return bool(get_cv_info().get("exists"))


@st.cache_data(ttl=30, show_spinner=False)
def _search_count() -> int:
    try:
        return len(json.loads(get_param("linkedin_searches") or "{}").get("searches") or [])
    except (ValueError, AttributeError):
        return 0


def _steps() -> list[tuple[bool, str, str]]:
    """(done, what to do, where)."""
    key_set = bool((library.settings().get("LLM_API_KEY") or {}).get("set"))
    health = library.health()
    has_run = bool(health.get("last_run") or health.get("current_run"))
    return [
        (key_set, "Add your AI API key", "Settings → Config"),
        (_cv_exists(), "Upload your CV (.docx)", "Settings → CV"),
        (_search_count() > 0, "Add a LinkedIn search", "Settings → Searches"),
        (has_run, "Run the job search once", "Settings → Workflow → Run now"),
    ]


def render_getting_started():
    steps = _steps()
    done = sum(1 for ok, _, _ in steps if ok)
    if done == len(steps) or st.session_state.get(HIDE_KEY):
        return

    with st.container(border=True):
        st.markdown(f"**Getting started** · {done} of {len(steps)} done")
        st.progress(done / len(steps))
        for ok, title, detail in steps:
            icon = ":material/check_circle:" if ok else ":material/radio_button_unchecked:"
            st.markdown(f"{icon} **{title}** · {detail}")
        go_col, guide_col, hide_col, _ = st.columns([1.6, 1.6, 1.6, 2.4])
        if go_col.button("Open Settings", icon=":material/settings:", width="stretch",
                         key="getting_started_go"):
            goto("Settings")
            st.rerun()
        if guide_col.button("Setup guide", icon=":material/menu_book:", width="stretch",
                            key="getting_started_guide"):
            _guide_dialog("Setup")
        if hide_col.button("Hide for now", width="stretch", key="getting_started_hide",
                           help="Comes back on reload until setup is done."):
            st.session_state[HIDE_KEY] = True
            st.rerun()


# The guide is opt-in reading, so it carries the detail the pages leave out. Every claim
# here mirrors the code: board hosts from scrapers/companies.py, the feed filter from
# scrapers/base.py, section names from settings_tab.py. Change them together.
SETUP = """
Four steps, about five minutes. The checklist on top ticks them off as you go.

**1. Connect an AI provider** · Settings → Config → LLM provider
Pick a provider (Google Gemini has a free tier), keep or change the model, paste your
API key, then **Save provider**. The AI scores every job and writes the cover letters.

**2. Upload your CV** · Settings → CV → Upload CV
Word `.docx` only. Every job is scored against it. On the first run the AI pulls
**CV keywords** (job titles and skills) from it; you can edit them on the same tab.

**3. Choose where jobs come from**
- **LinkedIn**: Settings → Searches. One row per search: keyword, location, experience,
  workplace, job type, posted within, easy apply.
- **Remote feeds** (RemoteOK, Himalayas, We Work Remotely): nothing to set up.
- **Companies you like**: star them on the Companies page and add a careers link.
  See the *Companies* tab of this guide for which links work.
- Turn any source on or off in Settings → Workflow → Sources.

**4. Run it once** · Settings → Workflow → Run now
Scoring waits 20 seconds between jobs to stay inside free AI limits, so a first run can
take a while. Matches appear on the Jobs page as they are scored. After that the
schedule runs it for you (daily at 01:00 by default).

**Optional**
- **Run summaries** to Telegram or Discord: Settings → Config → Notifications.
- **Auto-apply by email**: Settings → Config → Email. Read *How it works* first.
"""

HOW_IT_WORKS = """
#### What happens on each run
1. **Collect** from every source that is on.
2. **Skip** jobs already seen before and companies you blocked.
3. **Filter feed jobs** (RemoteOK, Himalayas, We Work Remotely) by your CV keywords:
   a job stays if its title matches one of your titles, or it mentions at least two of
   your skills. LinkedIn searches and company boards skip this filter, since you chose
   them. With no keywords at all, every feed job is dropped.
4. **Cap** the intake: jobs per run and per source (Settings → Workflow).
5. **Score** each job 0 to 100 against your CV and write a cover letter.
   At or above your match cutoff (60 by default) it counts as **Matched**.

**Pause** keeps the queue; **Resume** scores what is left without collecting again.
**Stop** ends the run; leftover jobs are scored on the next run.

#### Reading a job
- **Score** is the AI's verdict. *Why this scored* lists CV skills found in the
  posting; it is a keyword check, not the AI's reasoning.
- **Status** (Applied, Interview, Offer...) is only ever set by you and drives the
  Analytics funnel.

#### Things that act on their own
- **Auto-apply by email** (off by default): when a matched job asks for applications
  by email, the AI writes the email and sends it from your account with your CV
  attached. The status becomes *Email sent*.
- **Clean-up**: once a day, jobs and runs untouched for longer than *Keep jobs for*
  (60 days by default) are deleted. Starred and blocked companies are kept.
- **Public link** (sidebar): anyone with the link can open this dashboard. There is
  no login.

#### Words used across the app
| Word | Meaning |
|---|---|
| Queued | Collected, waiting to be scored. |
| Scored | The AI has rated it. |
| Matched | Scored at or above your cutoff. |
| Strong | Scored 80 or more. |
| New | You have not set a status yet. |
| CV keywords | Titles and skills that decide which feed jobs get scored. |
"""

COMPANIES = """
**Star** a company to mark its jobs with ★. **Block** one and its new jobs are never
scored. Jobs already scored stay, tagged Blocked.

#### Careers links
Add a careers link to a starred company and the app fetches jobs straight from it.
It checks the link once and the row says what it found.

| Link | Works? |
|---|---|
| `boards.greenhouse.io/acme` or `job-boards.greenhouse.io/acme` | Yes, Greenhouse. Most reliable. |
| `jobs.lever.co/acme` | Yes, Lever. |
| `jobs.ashbyhq.com/acme` | Yes, Ashby. |
| Company page that links to or embeds one of those boards | Yes, the board is detected. |
| Page with structured job data (built for Google Jobs) | Usually. Can break when the site is redesigned. |
| Workday, SmartRecruiters, other systems, pages that load jobs with JavaScript | Not supported. The row says why. |
| Site whose robots.txt disallows it | Not read, on purpose. |

**Best link:** open the company's job list, and if the address is on
greenhouse.io, lever.co or ashbyhq.com, paste that.

#### Row controls
- **In workflow**: fetch this company on every run. Needs *Company boards* on in
  Settings → Workflow → Sources.
- **Scrape now**: fetch once, right away, with or without *In workflow*.
- **Check again**: re-test a link that could not be read.
"""

SETTINGS_MAP = """
| To change | Go to |
|---|---|
| Run now, pause, stop, resume | Settings → Workflow → Job Pipeline |
| Schedule, clean-up time, days to keep jobs | Settings → Workflow → Schedule |
| Turn sources on or off | Settings → Workflow → Sources |
| Jobs per run, jobs per source | Settings → Workflow → How much to take in |
| AI provider, model, API key | Settings → Config → LLM provider |
| Match cutoff, wait between jobs | Settings → Config → Scoring |
| Auto-apply, sender name, SMTP account | Settings → Config → Email |
| Telegram, Discord | Settings → Config → Notifications |
| Upload or replace CV, edit CV keywords | Settings → CV |
| LinkedIn searches | Settings → Searches |
| We Work Remotely categories | Settings → Searches |
| Prompt that extracts CV keywords | Settings → Searches |
| Export, backup, delete all jobs | Settings → Data |
| Past runs and their logs | Settings → History |
| Starred and blocked companies, careers links | Companies |
| Timezone, ports, user id | `.env` file, then restart the stack |

Settings saved here apply from the next run. Values in `.env` are only read on first
start, except the ones in the last row.
"""

GUIDE_TABS = {
    "Setup": SETUP,
    "How it works": HOW_IT_WORKS,
    "Companies": COMPANIES,
    "Where settings live": SETTINGS_MAP,
}


@st.dialog("Find Me a Job guide", width="large")
def _guide_dialog(start: str = "Setup"):
    for tab, body in zip(st.tabs(list(GUIDE_TABS), default=start), GUIDE_TABS.values()):
        with tab:
            st.markdown(body)


def render_guide_button():
    with st.sidebar:
        if st.button("How it works", icon=":material/help:", width="stretch", key="open_guide",
                     help="Setup steps, how runs work, and where every setting lives."):
            _guide_dialog("How it works")
