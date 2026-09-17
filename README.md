# Find Me a Job - AI-Powered Job Scraper & Matcher

An automated job scraping and AI matching pipeline that runs on a schedule, scrapes jobs from **LinkedIn**, **RemoteOK**, **Himalayas**, **We Work Remotely** and the **careers pages of companies you choose**, prevents fetching the same job twice — including the same role arriving from two different sources — scores each one against your CV using an LLM, generates a cover letter for good matches, stores matched jobs in a **local SQLite database**, and serves them through a **Streamlit dashboard** with analytics, filtering, and job management. A **Cloudflare Quick Tunnel** exposes the dashboard publicly, and **Telegram notifications** send you the access URL on startup plus a summary after each run. Everything runs locally in Docker.

---

## Table of Contents

- [Features](#features)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables-env)
  - [LinkedIn Search Config](#linkedin-search-config)
  - [LLM Keywords Config](#llm-keywords-config)
- [What reaches the scorer](#what-reaches-the-scorer)
- [AI Scoring Logic](#ai-scoring-logic)
- [Choosing an LLM Provider](#choosing-an-llm-provider)
- [Database Schema](#database-schema)
- [Dashboard](#dashboard)
  - [Settings tab](#settings-tab)
  - [Blocking companies](#blocking-companies)
- [Python API Reference](#python-api-reference)
- [Estimated Token Usage Per Job](#estimated-token-usage-per-job)
- [Docker Services](#docker-services)
  - [Tests](#tests)
- [Download Size](#download-size)
- [License](#license)

---

## Features

- **Six sources** - LinkedIn (with filters), RemoteOK, Himalayas, We Work Remotely, and the careers pages of companies you add; each switchable from Settings
- **Company boards** - paste a company's careers URL and the app works out what is behind it. Greenhouse, Lever and Ashby boards are read through their own APIs, so you get the original description and the real application form, usually before the posting reaches a job site
- **Multiple LinkedIn searches** - define multiple search queries (different keywords, locations, filters) in a single config file; all are executed in one run
- **Deduplication** - jobs already seen or pending are skipped across runs, and the same role arriving from two different sources is recognised as one job rather than two
- **Intake limits** - the big feeds offer far more jobs than are worth scoring, so a run takes a set number and no more; feed jobs are keyword-checked against your CV for free before any of them costs an AI call
- **AI scoring** - scores each job 0–100 based on your CV, required skills, and years of experience; small experience gaps (1–2 years) are penalized lightly, 3+ years below means score 0
- **Cover letter generation** - only generated for jobs scoring above `FILTERING_SCORE` (default 60), saving tokens
- **Streamlit dashboard** at `localhost:8501` with analytics (stat cards, charts, a year-long activity heatmap), a scannable job list with a detail panel, quick-filter views, bulk actions, a combined starred/blocked companies list, and manual job entry
- **Auto email application** - when a job listing includes an email address, the pipeline sends a personalized application email with your CV attached and marks the job as `email_sent`
- **Cloudflare Quick Tunnel** - auto-creates a public `trycloudflare.com` URL for the dashboard, no account needed
- **Telegram notifications** - sends the dashboard URL on startup and a summary after each pipeline run
- **LLM-powered keyword extraction** - extracts job titles and skills from your CV to filter the feeds; cached and only re-extracted when the CV changes
- **Flexible LLM provider** - any OpenAI-compatible API (Groq, Google AI Studio, OpenRouter, local models, etc.)
- **Company blocklist** - block a company and its jobs are dropped before they ever reach the LLM, so they cost nothing
- **Starred companies** - keep a watchlist with careers URLs and notes; starred jobs are flagged with ★ and get their own view. Starring and scraping are separate: you can follow a company's board without endorsing it, and star a company you cannot scrape
- **Settings tab** - configure the LLM provider, cutoff, email and notifications, toggle sources, upload your CV, edit search config, trigger a run, export your data, and download a database backup without leaving the dashboard
- **Run history** - every pipeline run is recorded with counts and errors, so a silent failure is visible
- **Persistent storage** - SQLite with Alembic migrations applied on startup; old records purged automatically

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- An LLM API key from any OpenAI-compatible provider (e.g., [Groq](https://console.groq.com), [Google AI Studio](https://aistudio.google.com), [OpenRouter](https://openrouter.ai)) - see [Choosing an LLM Provider](#choosing-an-llm-provider)
- A [Telegram Bot](https://t.me/BotFather) - optional, for run notifications
- Your CV as a `.docx` file

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/find-me-job.git
cd find-me-job
```

### 2. Configure and start

```bash
cp .env.example .env      # then fill in your values
chmod 600 .env            # it will hold your API keys
cp /path/to/your-cv.docx cv.docx
cp params/linkedin_searches.txt.example params/linkedin_searches.txt
docker compose up -d --build
```

See [Environment Variables](#environment-variables-env) for what each setting does. Only the
container wiring has to be right before the first start; the LLM key, scoring, notifications and
email are filled in from **Settings → Config** once the dashboard is up, or seeded in `.env`
beforehand if you prefer.

### 3. Open the dashboard

Open [http://localhost:8501](http://localhost:8501). Everything is configurable from the **Settings** tab — upload your CV, edit your LinkedIn searches, and trigger a run.

The pipeline runs automatically on schedule and can be triggered manually from the dashboard. A public `trycloudflare.com` URL is also created automatically and sent to your Telegram.

![Telegram Tunnel Notification](assets/telegram-tunnel-notification.png)

---

## Configuration

### Environment Variables (`.env`)

**`.env` is a first-boot seed, not the live configuration.** The first time the database is
created, these values are copied into the `app_settings` table; from then on the table wins and
this file is ignored for those keys. Change a setting in the dashboard (**Settings → Config**),
not here — editing `.env` afterwards looks like it does nothing, because it does.

Five keys are the exception, because the containers are built with them and nothing re-reads them
at run time: `GENERIC_TIMEZONE`, `APP_UID`, `API_PORT` / `DASHBOARD_PORT`, `DB_PATH`, and the
dashboard's `API_URL`. The Config tab lists them as read-only for the same reason.

```env
# ── Container wiring (only editable here) ────────────
# Read when the stack starts: the scheduler is built with the timezone, the rest
# is docker plumbing.
GENERIC_TIMEZONE=Africa/Cairo

# Host user id the API/dashboard containers run as; must own ./data (run: id -u)
APP_UID=1000

# Host ports. Change these if something else on your machine already uses them;
# containers always talk to each other on the internal ports, so nothing else breaks.
API_PORT=8001
DASHBOARD_PORT=8501

# ── First-boot seeds (all optional) ──────────────────
# Uncomment any of these to prefill the settings table on the very first boot.
# Leave them commented and the stack starts on its defaults, and you fill them in
# at Settings > Config — which is where they live from then on either way.
#
# LLM. The key is the only thing the app cannot work without.
# LLM_API_KEY=
# LLM_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
# LLM_MODEL=gemini-2.5-flash
#
# Scoring. FILTERING_SCORE is the match cutoff; SCORING_DELAY_SECONDS is the rate
# limit for free tiers, and the biggest lever on how long a run takes.
# FILTERING_SCORE=60
# SCORING_DELAY_SECONDS=20
# DELETE_OLD_JOBS_DAYS=60
#
# Intake limits. How many jobs a run may queue in total, and how many any one source
# may contribute. 200 jobs at a 20s delay is roughly 67 minutes of scoring.
# INTAKE_MAX_PER_RUN=200
# INTAKE_MAX_PER_SOURCE=80
#
# Schedule.
# PIPELINE_ENABLED=true
# PIPELINE_MODE=daily            # daily | interval
# PIPELINE_AT_TIME=01:00         # daily mode
# PIPELINE_EVERY_N_HOURS=6       # interval mode; 1, 2, 3, 4, 6, 8 or 12
# PIPELINE_AT_MINUTE=0           # interval mode, minute past the hour
# RETENTION_AT_TIME=00:00
#
# Notifications. Telegram needs both the id (@get_id_bot) and the token
# (@BotFather). The Discord webhook URL is the whole credential — anyone holding
# it can post to the channel, so treat it like a token.
# TELEGRAM_ID=123456789
# TELEGRAM_BOT_TOKEN=xxxxxxxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# DISCORD_WEBHOOK_URL=
#
# Email. AUTO_EMAIL sends real applications to real employers during a run: on is
# 1/true/yes/on, anything else including blank is off. Sent mail cannot be
# recalled, so leave it off until you have read a few generated letters.
# AUTO_EMAIL=
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=your@gmail.com
# SMTP_APP_PASSWORD=
# SENDER_NAME=
```

### LinkedIn Search Config

Edit `params/linkedin_searches.txt` (created from `params/linkedin_searches.txt.example`
during setup; it is git-ignored because it holds your own preferences and the dashboard
rewrites it). The file supports **multiple searches** in a single config - the pipeline loops over all entries in the `searches` array:

```json
{
  "searches": [
    {
      "Keyword": "Software Engineer",
      "Location": "Cairo, Egypt",
      "Experience Level": "Entry level, Associate",
      "Remote": "Remote, Hybrid, On-Site",
      "Job Type": "Full-time",
      "Last Posted": "r604800",
      "Easy Apply": ""
    },
    {
      "Keyword": "Software Engineer",
      "Location": "Germany",
      "Experience Level": "Entry level, Associate",
      "Remote": "Remote, Hybrid, On-Site",
      "Job Type": "Full-time",
      "Last Posted": "r604800",
      "Easy Apply": "true"
    }
  ]
}
```

Add as many search objects to the `searches` array as you need - each one runs as a separate LinkedIn query within the same workflow execution.

**Field reference:**

| Field | Example Values | Notes |
|-------|---------------|-------|
| `Keyword` | `"Python Developer"` | Job title or skill - single value |
| `Location` | `"Cairo, Egypt"` | City or country - single value |
| `Experience Level` | `"Entry level, Associate"` | Comma-separated, multiple allowed |
| `Remote` | `"Remote, Hybrid"` | Comma-separated, multiple allowed |
| `Job Type` | `"Full-time, Contract"` | Comma-separated, multiple allowed |
| `Last Posted` | `"r86400"` | `r86400`=24h, `r604800`=1 week, `r2592000`=1 month |
| `Easy Apply` | `"true"` or `""` | Any non-empty string enables it |

### LLM Keywords Config

Edit `params/llm_keywords_extract.txt` - a prompt template sent to the LLM along with your CV text. The LLM extracts:
- **`titles`** - 3–5 realistic job titles based on your experience level
- **`skills`** - 10–20 technical skills from your CV

These keywords filter the broad feeds — RemoteOK, Himalayas, We Work Remotely — so only matching
jobs enter the pipeline, and rejecting one costs nothing because the check is arithmetic rather
than an LLM call. Jobs from a company you added and from your own LinkedIn searches are not
filtered this way: you named those yourself. Results are cached and only re-extracted when your
CV changes.

---

## What reaches the scorer

The sources between them offer far more jobs than are worth scoring — one feed alone
carries over a hundred thousand — and every job that gets through costs one LLM call and
one `SCORING_DELAY_SECONDS` wait. So a run does not queue everything it finds:

1. **Companies are fetched first**, then the feeds. Order matters because a duplicate is
   resolved first-wins: when the same role exists on a company's board and in a feed, the
   copy that survives is the board's — the original description and the real application
   form, rather than a syndicated summary and a redirect.
2. **Feed jobs are keyword-checked** against the titles and skills extracted from your CV.
   This is arithmetic, not an LLM call, so rejecting a job here costs nothing. Jobs from a
   company you added and from your own LinkedIn searches skip this check: in both cases you
   already said what you wanted, and a sideways role your keywords miss is often the point.
3. **Two limits apply.** `INTAKE_MAX_PER_SOURCE` (default 80) stops one feed filling the
   run before the others are reached; `INTAKE_MAX_PER_RUN` (default 200) is the ceiling for
   the whole run. Both are edited in Settings → Workflow, which shows what they cost in
   minutes.
4. **The same role from two sources is queued once**, matched on a fingerprint of the
   normalised company, title and location — so "Acme, Inc." and "ACME" are one employer.
   The blocklist uses the same normalisation, which is why blocking *Acme* also blocks
   *Acme, Inc.*

Each source reports what it offered, what was kept, and what was dropped — split into
*irrelevant* and *over the cap* — in the run history. A filter set too tight and a dead
source look identical without those numbers.

---

## AI Scoring Logic

Each job is scored individually by the LLM using the following logic.

**Input to the model:**
- Your full CV text (extracted from `cv.docx`)
- The full job description
- Today's date (injected dynamically for calculating years of experience)

**Scoring rules:**

| Factor | Effect on Score |
|--------|----------------|
| Required skills present in CV | High positive |
| Required skills missing from CV | Negative |
| Nice-to-have skills present | Small bonus |
| Experience meets or exceeds requirement | No penalty |
| Experience 1–2 years below requirement | Slight penalty |
| Experience 3+ years below requirement | Score = 0, stop immediately |

**Output format:**
```json
{"score": 78, "coverLetter": "..."}
```

The cover letter is a 2-paragraph professional body - no name, address, or signature - so it works as a clean template you can customize before sending. Jobs scoring below `FILTERING_SCORE` (default 60) get an empty cover letter to save tokens.

---

## Choosing an LLM Provider

The workflow works with **any OpenAI-compatible API**. Configure your provider from **Settings → Config**, which sets three values (`.env` can seed them on first boot only):

| Variable | Description | Example |
|----------|-------------|---------|
| `LLM_API_KEY` | Your API key | `gsk_xxxx`, `AIzaSy...`, `sk-...` |
| `LLM_URL` | Chat completions endpoint | See examples below |
| `LLM_MODEL` | Model identifier | See examples below |

**Provider examples:**

| Provider | `LLM_URL` | `LLM_MODEL` | Free Tier |
|----------|-----------|-------------|-----------|
| Groq | `https://api.groq.com/openai/v1/chat/completions` | `llama-3.3-70b-versatile` | Yes |
| Google AI Studio | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` | `gemini-2.5-flash` | Yes |
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` | `meta-llama/llama-3.3-70b` | Some models |
| OpenAI | `https://api.openai.com/v1/chat/completions` | `gpt-4o` | No |
| Anthropic (via proxy) | Any OpenAI-compatible proxy URL | `claude-sonnet-4-20250514` | No |
| Local (Ollama) | `http://host.docker.internal:11434/v1/chat/completions` | `llama3` | N/A |

> **For the best scoring and cover letter quality**, consider using **Claude Sonnet** or **GPT-4o** on the paid tier. The difference in cover letter coherence and scoring nuance is significant compared to free-tier models.

---

## Database Schema

```sql
-- Jobs fully processed in previous runs (long-term deduplication)
CREATE TABLE seen_jobs (
  id           TEXT PRIMARY KEY,  -- "linkedin_4384934676", "greenhouse_stripe_12345"
  seen_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  -- sha256 of normalised company::title::location, so the same role syndicated by a
  -- second source is recognised as one job. Null for rows written before this column
  -- existed and no longer present in filtered_jobs or pending_jobs — there is nothing
  -- left to compute one from. A null never matches, so those rows dedupe on id alone.
  fingerprint  TEXT               -- indexed
);

-- Jobs discovered this run, waiting to be scored by the LLM
CREATE TABLE pending_jobs (
  id          TEXT PRIMARY KEY,
  title       TEXT,
  company     TEXT,
  location    TEXT,
  applylink   TEXT,
  description TEXT,
  website     TEXT,             -- "linkedin", "remoteok", "Himalayas", "Greenhouse"…
  easy_apply  BOOLEAN DEFAULT FALSE,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Jobs scored by the LLM, displayed in the local dashboard
CREATE TABLE filtered_jobs (
  id           TEXT PRIMARY KEY,
  title        TEXT,
  company      TEXT,
  location     TEXT,
  applylink    TEXT,
  description  TEXT,
  website      TEXT,
  score        INTEGER,           -- 0–100 AI match score
  application_document TEXT,     -- generated cover letter / application text (nullable)
  easy_apply   BOOLEAN DEFAULT FALSE,
  ai_status    TEXT,              -- "fit" or "not_fit"
  user_status  TEXT DEFAULT 'new', -- see the user status list below
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Every user_status transition, for the job card timeline
CREATE TABLE job_status_history (
  id         INTEGER PRIMARY KEY,
  job_id     TEXT REFERENCES filtered_jobs(id),
  status     TEXT NOT NULL,
  changed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Companies you starred in the dashboard (names stored lowercase)
-- The company list. The table name is historical: rows are no longer only starred ones,
-- because "I want to work here" and "scrape this every run" are two separate facts.
CREATE TABLE starred_companies (
  id                INTEGER PRIMARY KEY,
  company_name      TEXT NOT NULL UNIQUE,
  careers_url       TEXT,
  notes             TEXT,
  created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  starred           BOOLEAN NOT NULL DEFAULT TRUE,   -- I want to work here
  in_workflow       BOOLEAN NOT NULL DEFAULT FALSE,  -- fetch this company every run
  fetch_method      TEXT NOT NULL DEFAULT 'unknown', -- unknown | ats | page | unreadable
  fetch_note        TEXT,                            -- why, when unreadable
  ats               TEXT,                            -- greenhouse | lever | ashby
  ats_token         TEXT,                            -- board token from the careers URL
  last_scraped_at   DATETIME,
  last_job_count    INTEGER,
  consecutive_empty INTEGER NOT NULL DEFAULT 0       -- two in a row switches the row off
);

-- One row per scraper, so a source can be turned off from the dashboard. Reconciled
-- from the scraper registry at startup; a source with no row here counts as enabled.
CREATE TABLE sources (
  name       TEXT PRIMARY KEY,   -- companies | linkedin | remoteok | himalayas | weworkremotely
  label      TEXT NOT NULL,
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at DATETIME
);

-- CV hash and extracted keyword cache
CREATE TABLE cv_keywords (
  id         INTEGER PRIMARY KEY,
  cv_hash    TEXT NOT NULL,
  keywords   TEXT NOT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

```sql
-- Companies whose jobs are dropped before scoring
CREATE TABLE blocked_companies (
  id           INTEGER PRIMARY KEY,
  company_name TEXT NOT NULL UNIQUE,   -- lowercase
  reason       TEXT,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- One row per workflow run, for the dashboard's run history
CREATE TABLE workflow_runs (
  id           INTEGER PRIMARY KEY,
  trigger      TEXT,                   -- "schedule" or "manual"
  status       TEXT,                   -- "running", "success", "failed"
  started_at   DATETIME,
  finished_at  DATETIME,
  jobs_scraped INTEGER DEFAULT 0,
  jobs_scored  INTEGER DEFAULT 0,
  jobs_matched INTEGER DEFAULT 0,
  error        TEXT
);
```

**User statuses:** `new`, `applied`, `email_sent`, `referral`, `assessment`, `interview`, `offer`, `rejected`, `wont_apply`. The analytics treat `applied`, `email_sent`, and `referral` as the "applied" bucket.

Schema is managed by **Alembic migrations**, applied automatically on each container startup. A brand-new database is created directly from the models and stamped at the current revision, so a fresh clone starts cleanly. `filtered_jobs` is indexed on every column the dashboard filters and sorts by, so page loads stay fast as the table grows. Records older than `DELETE_OLD_JOBS_DAYS` (default **60**) days are automatically purged on startup and daily at the time set in Settings (default **00:00**).

**Viewing the database:** The file lives at `./data/db/jobs.db` on your host. Open it directly in [DBeaver](https://dbeaver.io/) - select SQLite, browse to the file, and connect. No server or credentials needed.

---

## Dashboard

The project includes a **Streamlit dashboard** at [http://localhost:8501](http://localhost:8501) for browsing and managing your matched jobs.

| Analytics Tab | Jobs Tab |
|:---:|:---:|
| ![Analytics](assets/streamlit-analytics.png) | ![Jobs](assets/streamlit-jobs-table.png) |

> The screenshots above predate the current visual design.

The interface uses a single validated colour palette defined in `dashboard/src/theme.py`.
Categorical hues are assigned in fixed order, magnitude always uses one hue getting
darker (never a red-to-green rainbow), and the theme is pinned in
`dashboard/.streamlit/config.toml`. Charts carry legends and direct labels, so colour
never carries meaning on its own.

### One vocabulary

Every screen uses these words for these sets, and every count comes from one
function (`dashboard/src/library.py`) so two pages can never disagree:

| Term | Means |
|------|-------|
| **Queued** | Scraped, waiting for the scorer — a row in `pending_jobs`, not yet in Jobs |
| **Scored** | A row in `filtered_jobs` with a match score |
| **Matched** | Scored at or above `FILTERING_SCORE`. The scorer writes `ai_status="fit"` at exactly that line, so *Matched* and *at or above the cutoff* are the same set |
| **Strong match** | Scored 80 or above |
| **New** | Scored, still at application status *New* |
| **Status** | Where your application stands: New → Applied → … → Offer / Rejected |

Score bands are identical everywhere — **≥ 80 strong**, **≥ cutoff matched**,
**below cutoff** — and the same chip renders them in the list, the detail and the
histogram.

### Sidebar

Navigation with live counts, and the health of the pipeline on every page:

```
● Workflow inactive
Queue 53
Last run never
Counts updated just now
```

**Public link** sits underneath and states what it exposes before it shows you the
URL: a Cloudflare quick tunnel serves the whole dashboard — CV download, every job,
your statuses, and Settings including the danger zone — to anyone with the link, with
no password.

### Pages

- **Analytics** — six KPI tiles, then **Needs attention**: real conditions with somewhere to go (*"the workflow is inactive and 53 jobs are waiting"*, *"5 strong matches you have not opened"*), each of which hides itself once it stops being true. Then the full chart set — match rate, score distribution with your cutoff and median drawn on it, conversion funnel, status breakdown, applications by source, companies by best score, and a 365-day activity calendar
- **Jobs** — a scannable list. Six view chips (**All**, **Matched**, **Strong**, **New**, **⚡ Easy Apply**, **★ Starred**) with live counts, a search box, a sort control, and a **Filters** popover holding a score range, application status, AI verdict, source, location and company
- **Companies** — one compact table covering both lists, with **jobs seen**, **best score** and **last seen** pulled from your jobs table, and — for a starred company with a careers URL — what we can read from that page and the two controls for fetching it
- **Settings** — a control room: run the workflow, replace the CV, edit searches, export, and read run history

Working with jobs:

- **Defaults are neutral.** Nothing is filtered until you filter it, so a list labelled *All* is never a filtered list
- **Active filters are always visible** as removable chips under the search bar, and the count line states the remainder: `Showing 5 of 5 jobs · 5 hidden by filters`
- **Score chip** — one band-coloured number, no progress bar. At 95 / 90 / 90 / 85 / 80 the bars were the same bar
- **Why this score** — each row lists the CV skills the posting actually names, and the detail dialog leads with them. This is a keyword overlap against the skills extracted from your CV, not the scorer's reasoning: the scoring step records a score and a cover letter and no rationale, and the UI says so
- **Status from the row** — set Applied without opening anything. This is what feeds the funnel, the status breakdown and the activity calendar
- **Row link** — the ↗ at the right of every row opens the posting in a new tab. It sits at the same x on every row, so it is a fixed target
- **Detail panel** — click a title and it opens in a column beside the list, not a modal over it: nothing dims, and the rows stay readable for comparison. It only exists once a job is picked, so an unopened list keeps the full width and opening one widens the page rather than halving the list. The panel is sticky, so it stays level with you as you scroll. Inside: match evidence, apply link, star/block, status, the description with its bullets restored and your matched skills highlighted, the generated application document with a one-click PDF export, and a timeline of every status change
- **Bulk actions** — flip the **Select** toggle, tick rows, then set a status, star/unstar, block, or delete them in one go
- **Add job** — for a job you found yourself, so it shows up in the pipeline and analytics

Working with companies:

- **The effect is stated on the page.** Starring marks a company and gives it its own view; it does **not** change scoring. Blocking drops new postings before the scorer sees them, so they never cost an LLM call — jobs already in your list stay
- **Fetching a company's jobs.** Add a careers URL and the app checks what is behind it in the background, then says so on the row: a *Greenhouse / Lever / Ashby board detected* (one request, full descriptions, the real application form), *reading the page directly* (no board, but the page publishes structured job data), or *we cannot read jobs from this page* with the reason — usually listings rendered in the browser, or a `robots.txt` that asks us not to. An expander on the page explains all of this without a hover
- **Two independent controls.** **In workflow** fetches that company on every run and is unavailable while a page cannot be read, because turning it on would add nothing but a silent zero to every run. **Scrape now** fetches that one company immediately whatever the switch says, which is how you try a careers URL before committing it to every night. Neither needs the other, and neither is the same as starring
- **A company that goes quiet turns itself off.** Two empty fetches in a row and the row moves to *cannot read* with a note, rather than being retried nightly forever. **Check again** re-runs the check after a site redesign
- **Nothing is lost when a page cannot be read.** Large employers often run their own job software that nothing can read automatically; those roles still reach you through LinkedIn, Himalayas and the other feeds
- **Add from your jobs** — the Add dialog opens on the companies already in your database, with each one's best score and job count, so a list cannot fragment into `TP` and `TP Egypt` through hand-typing. A manual tab sits behind it
- **Absences stay quiet** — an empty cell rather than *"Careers URL not set"*

### Settings tab

A control room rather than a preferences pane. A live status strip sits above six tabs:

**Status strip** — polls in an `st.fragment`, so it updates without rerunning the page
or losing your scroll position. It reads the same counts as the sidebar and Analytics:

| Readout | Source |
|---------|--------|
| **Last run** | Newest row in `workflow_runs` — status, relative time, scored/matched counts, duration |
| **Scored** | `filtered_jobs` total, with the matched count underneath |
| **Queue** | `pending_jobs` depth — the number that moves while a run is in flight |

| Tab | What it does |
|-----|--------------|
| **Workflow** | **Run now** triggers the pipeline and narrates the attempt in an `st.status`. Includes live progress with a countdown during rate-limit waits. Failures become a persistent block naming the cause. Below it: the schedule, the retention window, a switch per source, and the intake limits with a live estimate of how long a full intake takes to score |
| **Config** | The LLM provider (presets or a custom OpenAI-compatible endpoint), the match cutoff and scoring delay, the SMTP account with a test send, and Telegram/Discord with a test per channel. Secrets are write-only — a stored one shows as `stored, ends abcd` with an explicit **Clear**. The keys that can only live in `.env` are listed here read-only, with the reason |
| **CV** | `cv.docx · 2.6 MB · file changed 27 Mar 2026 (4mo ago)`, the extracted titles and skills as chips (`4 titles · 18 skills · extracted 5mo ago` — a different event, so a different label), a download button, and the uploader collapsed behind **Replace CV** with a size diff and an explicit confirm |
| **Searches** | `params/linkedin_searches.txt` as an editable table — one row per LinkedIn query, with `f_TPR` values shown as *Past week* and Easy Apply as a checkbox. The keyword-extraction prompt sits below it. **Save changes** stays disabled until something actually changes, and the heading turns to `● Unsaved changes` when it does |
| **Data** | One export control (CSV/JSON × matched/all) that states row count and estimated size before you click, plus a one-click DB backup. Both generate lazily, so opening the tab exports nothing. Backups stream to your browser and are not kept server-side, which the tab says rather than leaving you to wonder where the history is |
| **History** | Runs table with a matched-per-run sparkline, a failed-only filter, and row-select for the raw run record. Empty until the workflow reports in — the empty state says exactly what to check |

The **Danger zone** at the bottom of **Data** clears the jobs table. It requires typing
`delete all jobs` and states the blast radius first. Note that the Cloudflare tunnel exposes the
dashboard without authentication — if you share that URL, you share this button too.

### Blocking companies

Blocking is enforced in the API at `POST /api/jobs/pending`, not in the scrapers — so every
source gets it automatically and a blocked company never costs an LLM call. Blocked jobs are
still recorded in `seen_jobs` so they are not re-fetched on every run, which means unblocking
affects future postings rather than retroactively restoring old ones.

The page auto-refreshes every 5 minutes. API responses are cached briefly in the dashboard, so a refresh does not re-query everything; any action you take clears the caches it affects.

---

## Python API Reference

The API runs on port `8001`. From your host use `http://localhost:8001`.

All endpoints are prefixed with `/api`. On startup, the API automatically runs Alembic migrations, seeds `app_settings` from the environment, reconciles the `sources` table from the scraper registry, and purges old records. Both the pipeline and the cleanup then run on the schedule stored in `app_settings` and edited from the dashboard's Settings → Workflow tab.

**Jobs** (`/api/jobs`):

| Method | Endpoint | Params / Body | Description |
|--------|----------|---------------|-------------|
| `GET` | `/api/jobs/exists` | `?jobid=linkedin_123` | Returns `{"exists": true/false}` |
| `POST` | `/api/jobs/pending` | JSON body | Insert a new job into pending_jobs |
| `GET` | `/api/jobs/pending` | - | List all pending jobs |
| `POST` | `/api/jobs/filtered` | JSON body | Move job from pending → filtered_jobs with score and cover letter |
| `GET` | `/api/jobs/filtered` | `?ai_status=fit&user_status=new&easy_apply=true&min_score=0&max_score=100&search=...&company=...&website=...&location=...&starred_only=false&sort_by=updated_at&sort_order=desc&page=1&page_size=20&include_body=true&include_keywords=false` | Paginated, filterable, sortable job list. `include_body=false` omits `description` and `application_document` — the dashboard uses this for the list and fetches the full record only when you open a job. `include_keywords=true` adds a `keywords` array per row — the CV skills that appear in that posting. `page_size` is capped at 200. |
| `GET` | `/api/jobs/filtered/options` | - | Distinct company and website values for filter dropdowns |
| `GET` | `/api/jobs/filtered/{jobid}` | - | Get a single filtered job by ID |
| `PATCH` | `/api/jobs/filtered/{jobid}/status` | `{"user_status": "applied"}` | Update user tracking status (see the [user status list](#database-schema)). 404 if the job does not exist. Setting the current status again is a no-op that writes no history |
| `GET` | `/api/jobs/filtered/{jobid}/history` | - | Full `user_status` transition timeline for one job |
| `GET` | `/api/jobs/filtered/{jobid}/match` | - | `{matched, missing, skills_known}` — which of the skills extracted from your CV this posting names. A literal keyword overlap, **not** the scorer's reasoning: the scoring node returns only `{score, coverLetter}` |
| `DELETE` | `/api/jobs/filtered/{jobid}` | - | Delete a job from filtered_jobs |
| `GET` | `/api/jobs/stats` | - | Aggregate counts (total, one count per AI and user status, `avg_score`, `median_score`, `easy_apply`) |
| `GET` | `/api/jobs/stats/daily-applied` | `?days=7` | Daily application counts for the last N days (max 730), read from `job_status_history` so a job that has since moved on to Interview still counts on the day it was applied to |
| `GET` | `/api/jobs/stats/funnel` | - | `{matched, applied, interviewing, offers, events}` counted as *ever reached*, from the status log — a funnel counts arrivals, so a later stage never shrinks an earlier one |
| `GET` | `/api/jobs/stats/by-source` | - | Total and applied counts grouped by source website |
| `GET` | `/api/jobs/stats/score-distribution` | - | Score histogram in 10-point bins, computed in SQL |
| `GET` | `/api/jobs/stats/top-companies` | `?limit=20` | Per company: `job_count`, `best_score`, `last_seen`, ranked by best score then volume (max 100) |

**Email** (`/api/email`):

| Method | Endpoint | Params / Body | Description |
|--------|----------|---------------|-------------|
| `POST` | `/api/email/send` | JSON body | Send an application email with CV attached via SMTP |

**CV** (`/api/cv`):

| Method | Endpoint | Params / Body | Description |
|--------|----------|---------------|-------------|
| `GET` | `/api/cv` | - | Extract and return text from cv.docx |
| `GET` | `/api/cv/check/{cv_hash}` | - | Check if a CV hash exists in keyword cache |
| `GET` | `/api/cv/keywords` | - | Get cached keywords and CV hash |
| `POST` | `/api/cv/keywords` | `{"cv_hash": "...", "keywords": "..."}` | Save/update keyword cache |

**Params** (`/api/params`):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/params/dashboard-url` | The public `trycloudflare.com` URL detected at startup (404 until the tunnel is up) |
| `GET` | `/api/params/{name}` | Read and return `params/{name}.txt`. `{name}` must match `[A-Za-z0-9_-]+`. |

**Starred companies** (`/api/starred`):

| Method | Endpoint | Params / Body | Description |
|--------|----------|---------------|-------------|
| `GET` | `/api/starred` | `?search=acme` | List starred companies |
| `GET` | `/api/starred/names` | - | All starred names (lowercase), for bulk client-side checks |
| `GET` | `/api/starred/check` | `?company=Acme` | Returns `{"is_starred": true/false}` |
| `POST` | `/api/starred` | `{"company_name": "...", "careers_url": "...", "notes": "..."}` | Add a company (409 if already starred, including a second tab racing the first). 422 on a blank name or a `careers_url` that is not http(s) |
| `POST` | `/api/starred/toggle` | `{"company_name": "..."}` | Star if missing, unstar if present. 422 on a blank name |
| `PATCH` | `/api/starred/{id}` | `{"careers_url": "...", "notes": "..."}` | Update URL / notes. 422 on a `careers_url` that is not http(s) |
| `DELETE` | `/api/starred/{id}` | - | Remove a starred company |

**Companies** (`/api/companies`) — the same rows as `/api/starred`, addressed as the company
list that Phase 2's fetching works over:

| Method | Endpoint | Params / Body | Description |
|--------|----------|---------------|-------------|
| `GET` | `/api/companies` | - | Every company with its fetch verdict: `fetch_method`, `fetch_note`, `ats`, `in_workflow`, `starred`, `last_scraped_at`, `last_job_count` |
| `PATCH` | `/api/companies/{id}` | `{"in_workflow": true, "starred": false, "careers_url": "..."}` | Partial update. Turning `in_workflow` on returns **409** when the careers page has not been checked or cannot be read — the switch cannot claim something the app cannot do. A new `careers_url` resets the verdict to `unknown` and schedules a fresh check |
| `POST` | `/api/companies/{id}/scrape` | - | Fetch this one company now, whatever its switch says. Writes through the normal intake path, so blocklist, seen-jobs and fingerprint all apply. Returns `{queued, already_seen, blocked, found, over_cap}`. Opens **no** `workflow_runs` row — it is not a run |
| `POST` | `/api/companies/{id}/detect` | - | Check the careers URL again, in the background. Useful after a site redesign |

`fetch_method` is the row's verdict and has four states: `unknown` (not checked yet), `ats`
(a Greenhouse, Lever or Ashby board — one request, full descriptions), `page` (no board, but
the page publishes structured job data), and `unreadable` (listings are rendered in the
browser, or `robots.txt` asks us not to read them; `fetch_note` says which). Only `ats` and
`page` may be switched into the workflow.

**Blocked companies** (`/api/blocked`) — same shape as starred, but these are filtered out:

| Method | Endpoint | Params / Body | Description |
|--------|----------|---------------|-------------|
| `GET` | `/api/blocked` | `?search=acme` | List blocked companies |
| `GET` | `/api/blocked/names` | - | All blocked names (lowercase) |
| `GET` | `/api/blocked/check` | `?company=Acme` | Returns `{"is_blocked": true/false}` |
| `POST` | `/api/blocked` | `{"company_name": "...", "reason": "..."}` | Block a company (409 if already blocked, including a second tab racing the first). 422 on a blank name |
| `POST` | `/api/blocked/toggle` | `{"company_name": "..."}` | Block if missing, unblock if present. Matched like `/check`, so unblocking "Acme, Inc." also removes "acme". 422 on a blank name |
| `PATCH` | `/api/blocked/{id}` | `{"reason": "..."}` | Update the reason |
| `DELETE` | `/api/blocked/{id}` | - | Unblock |

**Runs** (`/api/runs`):

| Method | Endpoint | Params / Body | Description |
|--------|----------|---------------|-------------|
| `GET` | `/api/runs` | `?limit=20` | Recent workflow runs, newest first |
| `POST` | `/api/runs/trigger` | - | Run the pipeline now, in the background. 202, returns immediately; a run already in flight is skipped, not queued |
| `POST` | `/api/runs/pause` | - | Ask the active run to stop after the job it is on. 202, or 409 if no run is active. Unscored jobs stay queued |
| `POST` | `/api/runs/stop` | - | Kill the job being scored and end the run. 202, or 409 if no run is active. Not resumable |
| `POST` | `/api/runs/resume` | - | Score the leftover queue without re-scraping. 202, or 409 if the newest run is not `paused` |
| `GET` | `/api/runs/current` | - | Live progress of the active run, or `null`. Includes `stage`, `detail`, `done`/`total`, `seconds_remaining` during a scoring wait, and the last 5 events |
| `GET` | `/api/runs/{id}/events` | - | Full event history for one run |

**Settings** (`/api/settings`):

| Method | Endpoint | Params / Body | Description |
|--------|----------|---------------|-------------|
| `GET` | `/api/settings` | - | Every application setting as one flat object. Secret keys come back as `{"set": true, "hint": "…abcd"}` — no endpoint ever returns a stored credential |
| `PUT` | `/api/settings` | `{"LLM_MODEL": "gpt-4o-mini", "FILTERING_SCORE": 55}` | Partial update. 400 naming the key on an invalid or unknown one. On a secret, `""` means "leave unchanged" and `null` clears it. Writing `FILTERING_SCORE` re-labels existing jobs and returns `{"updated": [...], "reclassified": n}` |
| `POST` | `/api/settings/notifications/test` | `{"channel": "telegram"}` | Posts a fixed message through one channel and reports the HTTP result |
| `GET` | `/api/settings/schedule` | - | Current schedule, `next_run_at`, timezone, and any overlap `conflict` |
| `PUT` | `/api/settings/schedule` | `{"enabled": true, "mode": "interval", "every_n_hours": 3, "at_minute": 30, "at_time": "01:00", "retention_at_time": "00:00"}` | Partial update. Validates, stores, and reschedules live — no restart. 400 on an invalid value (times are ASCII `HH:MM`) or a daily time that collides with retention. The six schedule keys are refused by the generic `PUT` above, so there is one writer per key |

**Sources** (`/api/sources`):

| Method | Endpoint | Params / Body | Description |
|--------|----------|---------------|-------------|
| `GET` | `/api/sources` | - | Every registered scraper and whether the next run will use it |
| `PUT` | `/api/sources/{name}` | `{"enabled": false}` | Turn one source on or off. 404 on a name that is not registered. A source with no row counts as enabled |

### Scheduling

The pipeline runs daily at **01:00** and retention at **00:00** by default, both editable in
Settings → Workflow. Two modes: *once a day* at a set time, or *every N hours* where N is a
divisor of 24 (1, 2, 3, 4, 6, 8, 12) at a set minute past the hour. Intervals are anchored to the
wall clock, not to container start, so restarting never shifts the run times.

Changes apply immediately — the API reschedules the job in place. A run already in progress is
not affected; only the next fire moves. Turning the schedule off leaves the pipeline manual-only:
**Run now** and `POST /api/runs/trigger` keep working.

Settings live in the `app_settings` table, which the dashboard writes. On first boot, any matching
environment variables seed it; after that the table wins and `.env` is ignored for those keys.

Every interval that divides 24 includes midnight, so retention and the pipeline can always land on
the same minute. Rather than forbidding that, the two share the pipeline's run lock, and which one
yields depends on who got there first: retention finding a run in progress logs, skips, and purges
the next day; a run finding retention in progress waits up to two minutes for it to finish, because
a skipped run is a whole night of scraping lost with nothing to retry it. A run that does have to
be dropped is written to `workflow_runs` as failed, so it shows up in Run history rather than only
in the container log. Missed fires get an hour of
grace, so a machine that was asleep at the scheduled time runs the job once when it comes back
rather than waiting a full day.

Run `status` is one of `running`, `success`, `failed`, `paused`, `stopped`. `paused` is terminal
for that row: the workflow counts as paused while it is the newest run, the scheduled run skips
while it is, and resuming opens a new run instead of reopening it.

`stopped` is terminal too but deliberately not resumable. Pause waits for the job being scored to
finish and saves it, so the untouched queue is a clean cursor; stop shuts down the socket that
call is blocked on, so the job dies mid-flight with no result and no cursor to resume from.
Starting again is a full fresh run. A stop ends only its own run — unlike a pause, it does not
hold the nightly schedule.

`GET /api/runs/current` also reports `pause_requested` and `stop_requested`, so the dashboard can
show an interrupt that has been asked for but not yet landed.

**Export and backup**:

| Method | Endpoint | Params | Description |
|--------|----------|--------|-------------|
| `GET` | `/api/jobs/export` | `?format=csv\|json&include_body=false` | Export filtered jobs; CSV is streamed |
| `GET` | `/api/backup` | - | Consistent snapshot of `jobs.db` via `VACUUM INTO`, safe while running |

**CV** additions:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/cv/upload` | Replace `cv.docx` (multipart). Validates the file parses before overwriting |
| `GET` | `/api/cv/info` | Size and mtime of the current CV |

**Params** additions:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `PUT` | `/api/params/{name}` | Overwrite `params/{name}.txt`. Only existing files can be replaced; 256 KB cap |

**Health**: `GET /health` returns `{"status": "ok"}` and backs the container healthcheck.

### `POST /api/jobs/pending`

```json
{
  "id": "linkedin_xxxxxxxx",
  "title": "Software Engineer",
  "company": "X Corp",
  "location": "Cairo, Egypt",
  "applylink": "https://linkedin.com/jobs/view/xxxxxxxx",
  "description": "We are looking for a software engineer...",
  "website": "linkedin",
  "easy_apply": false
}
```

### `POST /api/jobs/filtered`

Same fields as pending, plus `score`, `application_document`, and `ai_status`:

```json
{
  "id": "linkedin_xxxxxxxx",
  "title": "Software Engineer",
  "company": "X Corp",
  "location": "Cairo, Egypt",
  "applylink": "https://linkedin.com/jobs/view/xxxxxxxx",
  "description": "We are looking for a software engineer...",
  "website": "linkedin",
  "score": 82,
  "application_document": "I am excited to apply for...",
  "easy_apply": false,
  "ai_status": "fit"
}
```

### `POST /api/email/send`

```json
{
  "recipient": "hiring@company.com",
  "subject": "Application for Software Engineer",
  "body": "Dear Hiring Manager,\n\nI am excited to apply for..."
}
```

The email is sent via SMTP using the account set in **Settings → Config** (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_APP_PASSWORD`, `SENDER_NAME`). Your `cv.docx` is automatically attached. Turn on **Send applications automatically** there — `AUTO_EMAIL`, on for `1/true/yes/on` — to let the pipeline send application emails itself when a job listing provides an email address.

---

## Estimated Token Usage Per Job

### Job scoring & cover letter (every job)

One LLM call per *queued* job — scores it against your CV and generates a cover letter for fits.
Only jobs that pass the intake gate get this far, which is what keeps a large feed from turning
into a large bill: see [What reaches the scorer](#what-reaches-the-scorer).

| Component | Tokens (approx) |
|-----------|----------------|
| System prompt | ~300 |
| CV text | ~500–800 |
| Job description | ~500–1,000 |
| Output (score + cover letter) | ~400–600 |
| **Total** | **~1,700–2,700** |

### Email eligibility check (fit jobs with `AUTO_EMAIL` enabled)

A second LLM call runs only on jobs that scored ≥ `FILTERING_SCORE` **and** whose description contains an email hint. It receives the job description and the cover letter from step 1, determines whether the job actually requires applying via email, and if so extracts the recipient address and generates a professional application email body.

| Component | Tokens (approx) |
|-----------|----------------|
| System prompt | ~300 |
| Job description | ~500–1,000 |
| Cover letter (from scoring step) | ~200–400 |
| Job title + company + sender name | ~20–30 |
| Output (JSON with email body or false) | ~200–400 |
| **Total** | **~1,200–2,200** |

### Summary

| Scenario | LLM Calls | Tokens per job (approx) |
|----------|-----------|------------------------|
| Scoring only (`AUTO_EMAIL` off) | 1 | ~1,700–2,700 |
| Scoring + email check (`AUTO_EMAIL` on, job has email hint) | 2 | ~2,900–4,900 |

> **Note:** The email LLM call only runs on fit jobs whose description matches an email pattern — typically a small fraction of total scraped jobs. Most jobs still consume only the scoring tokens.

---

## Docker Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `find-me-job-python-api` | Custom (built from `python-api/Dockerfile` based on `python:3.12-slim`) | `8001` | FastAPI backend (SQLModel ORM, Alembic migrations, scrapers, LLM scoring, scheduling) |
| `find-me-job-dashboard` | Custom (built from `dashboard/Dockerfile` based on `python:3.12-slim`) | `8501` | Streamlit dashboard for analytics and job management |
| `find-me-job-tunnel` | `cloudflare/cloudflared:2026.3.0` | internal only | Cloudflare Quick Tunnel - exposes the dashboard via a public `trycloudflare.com` URL |

The API and dashboard containers run as a non-root user and expose a healthcheck; Compose waits for the API to report healthy before starting the dashboard. The container user id defaults to `1000`. If your host user id is different (check with `id -u`), set `APP_UID` in `.env` so the containers can write to `./data`:

```bash
echo "APP_UID=$(id -u)" >> .env
docker compose up -d --build
```

The tunnel container publishes no host port — the API reads the tunnel URL over the internal Docker network.

### Troubleshooting

**`Bind for 0.0.0.0:8001 failed: port is already allocated`** — something else on your
machine uses that port. Set `API_PORT` (or `DASHBOARD_PORT`) in `.env`
to a free one and bring the stack back up. Only the host-side port changes; the
containers keep talking to each other on the internal ports.

```bash
echo "API_PORT=8002" >> .env
docker compose up -d
```

**The tunnel never comes up / `failed to request quick Tunnel: ... i/o timeout`** — your
containers cannot resolve DNS. Check whether the Docker daemon pins a resolver your
network blocks:

```bash
cat /etc/docker/daemon.json                 # look for a "dns" override
docker run --rm alpine nslookup api.trycloudflare.com
resolvectl status | grep 'Current DNS'      # what the host actually uses
```

If the daemon's resolvers are unreachable, point the affected services at working ones
in a `docker-compose.override.yml` (gitignored, loaded automatically, no sudo needed):

```yaml
services:
  cloudflared:
    dns: [1.1.1.1, 8.8.8.8]   # replace with resolvers that work on your network
```

The stack still works without the tunnel — only the public URL and its QR code are
unavailable. The API keeps watching and picks the URL up whenever cloudflared succeeds.

**Never run this stack with `sudo`.** It writes root-owned files into `data/`, which
breaks the next normal start.

### Useful commands

```bash
docker compose up -d              # Start all services
docker compose up -d --build      # Rebuild images after code changes
docker compose logs -f python-api # Tail API logs
docker compose down               # Stop everything
docker compose down -v            # Stop and wipe all data (database)
```

### Tests

Two suites. The unit and API tests run inside the API image against in-memory SQLite:

```bash
docker compose exec python-api python -m pytest tests
```

`full-stack-tests/` is a Playwright suite that drives the real dashboard and API, so the
stack must be running and Node must be installed on the host:

```bash
cd full-stack-tests
npm install
npx playwright install chromium   # first time only
npx playwright test
```

It writes to the live `data/db/jobs.db`: every test creates `qa-e2e-*` rows and deletes
them afterwards, and tests run one at a time. A run killed midway can leave such a row
behind; remove it from the Companies page or with `DELETE /api/starred/{id}`.

---

## Download Size

Estimated download size on first `docker compose up -d`:

| Component | Download Size |
|-----------|---------------|
| Python base image (`python:3.12-slim`) (shared by API + dashboard) | ~50 MB |
| API pip dependencies (FastAPI, SQLModel, Alembic, httpx, beautifulsoup4) | ~30 MB |
| Dashboard pip dependencies (Streamlit, Plotly, pandas) | ~120 MB |
| Cloudflared image (`cloudflare/cloudflared:2026.3.0`) | ~30 MB |
| **Total download** | **~230 MB** |

`data/db/jobs.db` stays small — records older than `DELETE_OLD_JOBS_DAYS` are purged daily, along with their status history.

---

## License

MIT License - see [LICENSE](LICENSE) for details.
