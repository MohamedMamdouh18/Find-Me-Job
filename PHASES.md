# Find Me a Job — Next Four Phases

Sequenced plan written against the current codebase. Complements `ROADMAP.md`, which holds
the long-form option list; this file is the committed order of work.

Phase 1 is configuration: everything that still lives in `.env` moves into the database and
the dashboard. It goes first because every later phase adds knobs — sources to toggle, board
tokens to maintain, notification channels to point somewhere — and each one is cheaper to
build against a settings table that already exists than to retrofit afterwards.

---

## Already shipped

**n8n is gone.** The scheduler, the scrapers, the scoring loop and the notifications all run
inside `python-api`. `docker-compose.yml` has three services, `services/pipeline.py` is the
whole flow, and `run_events` + `RunContext.emit()` replaced n8n's execution view with
something greppable that outlives the run. Pause, stop and resume landed with it, along with
per-source and per-job failure isolation and unit tests over recorded scraper fixtures.

**The schedule is user-set.** `app_settings`, `services/settings.py` and
`services/settings_store.py` exist, and `PIPELINE_ENABLED`, `PIPELINE_MODE`,
`PIPELINE_EVERY_N_HOURS`, `PIPELINE_AT_MINUTE`, `PIPELINE_AT_TIME` and `RETENTION_AT_TIME`
are edited from Settings → Workflow. That is the first slice of Phase 1; the rest of Phase 1
is the other thirteen keys.

---

## Phase 1 — Everything configurable from the dashboard

**Goal.** A user never opens `.env` after first boot.

### What already exists

The mechanism is built and in production use for the schedule. Do not design a second one.

| Piece | Where | What it does |
|---|---|---|
| `app_settings` table | migration `a3f1c9b45e27` | flat `key`, `value`, `updated_at` |
| `SETTINGS` registry | `services/settings.py` | `Setting(default, parse)` per key — parse validates and converts |
| `raw_setting()` | `services/settings.py` | precedence: stored row → env var → literal default |
| `get_setting()` | `services/settings.py` | parsed value; an unparseable row falls back to the default rather than killing the scheduler |
| `seed_from_env()` | `services/settings_store.py` | one-time copy of env values into missing rows on boot, so an existing install keeps working untouched |
| `load_cache()` / `set_cache()` | `services/settings_store.py`, `settings.py` | process-global cache, rebound not mutated, refreshed after every write |

Adding a setting is therefore one row in `SETTINGS`, one call-site change from `os.getenv`
to `get_setting`, and a control in the dashboard. No migration per key — that is what the
flat key/value shape bought.

### What is left

**The other thirteen keys.** Everything in `services/settings.py` above the registry still
reads `.env` directly through a `get_*()` helper:

`LLM_URL`, `LLM_MODEL`, `LLM_API_KEY`, `FILTERING_SCORE`, `SCORING_DELAY_SECONDS`,
`DELETE_OLD_JOBS_DAYS`, `AUTO_EMAIL`, `SENDER_NAME`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_APP_PASSWORD`, `TELEGRAM_ID`, `TELEGRAM_BOT_TOKEN`.

Each helper keeps its name and signature and changes its body to `get_setting(...)`, so no
caller moves. The pipeline reads settings at the point of use, in process, so a change
applies to the next run with no restart.

`SCORING_DELAY_SECONDS` is on the list precisely because it is not in `.env.example` today —
it is invisible unless you read the source, and it is the single biggest lever on run length.

**`GENERIC_TIMEZONE` stays in `.env`.** APScheduler is constructed with it at startup and
the dashboard uses it as the container clock (`TZ`). Changing it at run time changes neither.
Say so in the UI rather than letting it look broken. The same goes for `APP_UID`, `API_PORT`,
`DASHBOARD_PORT` and `DB_PATH`, which are container wiring, not application settings.

### Secrets need a different read path

Four of the new keys are credentials: `LLM_API_KEY`, `SMTP_APP_PASSWORD`,
`TELEGRAM_BOT_TOKEN`, and the `DISCORD_WEBHOOK_URL` added below. The API is unauthenticated
and the tunnel exposes the dashboard publicly, so a `GET /api/settings` that echoes stored
values turns the settings page into a credential dump reachable by anyone with the tunnel
URL.

**Mark secret keys in the registry and never return their values.** `GET` returns
`{"set": true, "hint": "…abcd"}`; `PUT` accepts a new value, and an empty string means
"leave unchanged" rather than "clear" — otherwise a round-trip through the form wipes every
credential the page could not display.

### API and dashboard

`GET /api/settings` returns one flat object; `PUT /api/settings` takes a partial update and
returns 400 naming the key when `parse_setting` raises. The existing
`GET/PUT /api/settings/schedule` stays as the typed schedule endpoint — it has its own
conflict validation — and the generic pair covers everything else.

A **Providers** section in Settings. The LLM endpoint is a picker with presets plus free
text:

| Preset | URL |
|---|---|
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` |
| OpenAI | `https://api.openai.com/v1/chat/completions` |
| Anthropic | `https://api.anthropic.com/v1/chat/completions` |
| Groq / Together / OpenRouter | their OpenAI-compatible paths |
| Custom | free text |

Every call posts an OpenAI-shaped body, so the only hard requirement is an OpenAI-compatible
`/chat/completions` endpoint. Say that next to the Custom field — it is the difference
between "any provider" and "any provider that speaks this shape".

### Notification channels, including Discord

Notifications are settings-shaped, so they land here rather than in a phase of their own:
the credential moves into the table, the UI section is the same one, and the migration is
the same migration.

**Add Discord.** `DISCORD_WEBHOOK_URL` as a secret setting, and a webhook POST next to
`send_telegram()` in `shared.py`:

```python
httpx.post(webhook_url, json={"content": message[:1900]}, timeout=5)
```

Plain `content`, not an embed: all three call sites send run-shaped prose, not a job record.
Discord's hard limit is 2000 characters and a summary can exceed it, so truncate rather than
let the post 400.

**Fan out once.** There are three `send_telegram()` call sites — `pipeline.py:397` (run
summary), `emailing.py:105` (application sent), `shared.py:93` (tunnel URL). Replace them
with one `notify(message)` that walks the configured channels, each wrapped so a dead webhook
logs a warning and the run continues, exactly as `send_telegram()` already swallows its own
failures. A notification channel must never be able to fail a run.

**The webhook URL is the credential.** There is no separate token: anyone holding
`https://discord.com/api/webhooks/{id}/{token}` can post to the channel. So it is a secret
key by the rules above, and `redact_secrets()` in `services/run_context.py` needs a pattern
for it — the existing three cover bearer tokens, Telegram tokens and JSON key fields, and
would pass a webhook URL straight through into `run_events`.

A **Test** button per channel that posts a fixed message and reports the HTTP result is worth
the twenty lines. A silent notification channel is indistinguishable from a quiet night.

### `FILTERING_SCORE` leaves residue

Unique among the settings: `ai_status` is written at scoring time, not derived on read. A
job scored 55 under a cutoff of 60 is stored `not_fit` permanently, so lowering the cutoff
to 50 leaves the table holding two populations judged under different rules with nothing
marking which is which.

**Recompute on change** — the score is stored, so it is one `UPDATE` over `filtered_jobs`
whenever the setting is written. Cheaper than explaining an inconsistent table forever.

Also: `theme.py:68` reads `FILTERING_SCORE` at *module import*, so the dashboard must fetch
it per-run through `library.py`'s cache rather than keeping it as a module constant.

### Source toggles

A switch per site in the dashboard: a `sources` table (`name`, `label`, `enabled`) and one
check in the orchestrator, replacing the bare `SOURCES.items()` walk in `pipeline.py`:

```python
for name, fetch in enabled_sources():
    ...
```

Seed with `linkedin` and `remoteok`, both enabled, so upgrade behaviour is unchanged. This
is also what Phase 2 registers its ATS sources into, and what makes a per-source health
readout meaningful.

The case worth testing deliberately: **every source disabled**. Scoring reads the queue from
the database rather than from the scrapers, so a run with zero scrapers must still drain any
backlog rather than exiting early — the same path `trigger == "resume"` already takes.

### Done when

`.env` holds only `GENERIC_TIMEZONE`, `APP_UID`, the database path and the host ports.
Changing the LLM provider, key, model, cutoff, scoring delay, retention, email settings,
Telegram target, Discord webhook or enabled sources from the dashboard changes the next run
with no restart, and no endpoint returns a stored credential.

---

## Phase 2 — More sources

Everything downstream of `pending_jobs` is source-agnostic, so after Phase 1 a source is
exactly: one module implementing the `Source` protocol, one `website` value, one row in
`sources`. No workflow, no id, no redeploy.

### Which sources are real — verified, not assumed

Every row below was called live on 2026-09-16 with a plain polite `curl`, no auth, no browser
spoofing, no challenge solving. The survey with response shapes and the tokens used is at
`.scratch/phase-2-sources/endpoint-survey.md`. Endpoint shapes drift, so re-verify before
building rather than trusting this table a year from now.

**Ship these — one request, description already in the list response**

| Source | Endpoint | Company field | Note |
|---|---|---|---|
| Himalayas | `himalayas.app/jobs/api?limit=&cursor=` | `companyName` | 102,388 jobs, cursor paging, `applicationLink` |
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | board label | 647 jobs for one token; `content` is escaped HTML |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{token}` | board label | `descriptionPlain` — no HTML cleanup at all |
| We Work Remotely | `weworkremotely.com/remote-jobs.rss` + category feeds | inside `title` | split `Company: Role` apart |
| Lever | `api.lever.co/v0/postings/{token}?mode=json` | board label | body is `descriptionPlain` + `lists[]` + `additionalPlain`, all three |
| Recruitee | `{company}.recruitee.com/api/offers/` | `company_name` | also carries `requirements` |
| Workable | `apply.workable.com/api/v1/widget/accounts/{token}?details=true` | account | **not** `/api/v3/...`, which is POST-only and carries no description |

**Below the line — all N+1, wrong trade while `SCORING_DELAY_SECONDS` is the bottleneck**

SmartRecruiters (list carries neither description nor apply URL, only an API ref), BambooHR,
Breezy, Rippling. Personio answers on both `.jobs.personio.de` and `.jobs.personio.com` but is
XML and mostly German-language boards. Hacker News "Who is Hiring" is one Algolia request for a
month of roles, but every field has to come out of free prose with regex — worth a spike of its
own, not part of this phase.

**Out, with the reason**

| Source | Why |
|---|---|
| Indeed | `robots.txt` disallows most country job paths; a plain `curl` of the search page returns **403**; the old RSS endpoint returns **404**; the Publisher API is retired. What remains needs an approved partner account |
| Glassdoor | Same posture, and its value is reviews and salary rather than listings you cannot get elsewhere |
| FlexJobs | Paid subscription. Not probed at all — a paywall is a decision, not an obstacle |
| Wellfound | Turnstile challenge; `robots.txt` disallows `/search` |
| Hiring Cafe | Search API returns 401 without credentials; robots denies the job paths |
| Remote.co | Zero bytes over three attempts, apparent edge block; robots stance never retrieved |
| Remotive | **Skipped** (decision 8). Not refused — constrained: robots disallows `/api/*` and the ToS asks for **≤4 requests/day**. A daily rate limiter for one source whose catalogue overlaps Himalayas is the wrong first facility |

LinkedIn is already the most fragile source in the stack. Nothing in the "out" column multiplies
coverage enough to justify multiplying that fragility.

### Decisions settled

Ten questions were worked through before any of this was written down. They are binding; a
deviation needs a new decision, not a judgement call mid-implementation.

| # | Decision | Why |
|---|---|---|
| 1 | **A company is the unit, not an ATS.** `sources` rows are feeds plus one `companies` row. Greenhouse/Lever/Ashby are *fetch methods* on a company, never toggles of their own | See `docs/adr/0001`. Per-ATS sources walk the same company twice and split its health across two rows |
| 2 | A company row is walked **without** the relevance filter, but still under the cap | Starring a company is explicit intent; filtering it out is how the feature comes to look broken |
| 3 | On a duplicate, **first wins**. Companies and boards are walked before feeds so the better copy usually arrives first | Ranked replacement needs a rank column, fingerprints on two more tables, and delete-and-reinsert inside intake |
| 4 | One **`INTAKE_MAX_PER_RUN` budget** with a per-source ceiling under it. Defaults 200 and 80 | The global number is the one that maps to "how long will tonight take" |
| 5 | The careers-page sniff runs **in the background**, not in the save request | It fetches a third-party page; saving a URL must not be as slow as the slowest careers page on the internet |
| 6 | The generic ladder stops at **deterministic rungs**. No LLM on a careers page | An invented job costs a scoring call, a cover letter and a slot in the table, and looks exactly like a real one |
| 7 | First cut: feeds **Himalayas + We Work Remotely**, fetch methods **Greenhouse, Lever, Ashby**. Recruitee and Workable follow | Biggest coverage per module, and the three ATS parsers share one shape |
| 8 | **Remotive is skipped** | robots disallows `/api/*`, ToS asks ≤4 requests/day, catalogue overlaps Himalayas. A daily rate limiter for one source is the wrong first facility |
| 9 | A company row can exist **unstarred** | "Scrape this board" and "I want to work here" are different facts, and Phase 3 reads the star as a scoring signal. One boolean now beats a retrofit later |
| 10 | The table stays `starred_companies`; the concept is **Companies** | A rename touches migrations, repositories, routes and the dashboard for no user-visible gain |

### Fetch methods: the ATS boards

Greenhouse, Lever and Ashby are the strongest addition in the whole plan, and the reason is not
coverage — it is shape. They are documented JSON APIs with no auth, no rate limit worth the name
and no bot detection, serving the companies you actually want *first*, because the ATS is where
the posting is created before it is syndicated anywhere else.

The decisive detail: **the list call carries the full description.** One request per company for
every open role and its body. LinkedIn costs one request per search page plus one per job page
plus backoff, and can ban the egress IP; twenty-five ATS boards is twenty-five requests and
cannot.

None of them is a source. There is no public cross-company endpoint for any ATS — the only call
is per board token — so "scrape Greenhouse" is not a thing that can exist. What exists is "scrape
these boards", and the list of boards is the company list. Discovery of companies you have not
thought of is what the feeds are for, and those feeds are largely syndicating these same ATS
postings.

**Endpoints**

| ATS | URL | List path | Description field |
|---|---|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `jobs[]` | `content` — HTML, entity-escaped |
| Lever | `https://api.lever.co/v0/postings/{token}?mode=json&limit=100` | top-level array | `descriptionPlain` + `lists[]` + `additionalPlain`, all three |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{token}` | `jobPostingGroups[].jobPostings[]` | `descriptionPlain` |

**Field mapping to `PendingJobRequest`**

| Field | Greenhouse | Lever | Ashby |
|---|---|---|---|
| `id` | `greenhouse_{token}_{id}` | `lever_{token}_{id}` | `ashby_{token}_{id}` |
| `title` | `title` | `text` | `title` |
| `company` | company row | company row | company row |
| `location` | `location.name` | `categories.location` | `jobLocations[].name`, joined |
| `applylink` | `absolute_url` | `hostedUrl` | `https://jobs.ashbyhq.com/{token}/{id}` |
| `description` | `content` | the three keys, concatenated | `descriptionPlain` |
| `website` | `Greenhouse` | `Lever` | `Ashby` |

The company name comes from the stored company row, never from the payload — Greenhouse does not
reliably carry one, Lever and Ashby carry none at all, and Ashby's job URL has to be built from
the board token. Deriving either from a display name is how you get `jobs.ashbyhq.com/scaleai`
for "Scale AI".

**Implementation.** One module, `scrapers/companies.py`, holding a parser per fetch method and
one walk over the company rows. A single `SOURCES` entry — `companies` — so Phase 1's toggle
turns the whole walk on or off, and the per-company readout carries the detail that a per-ATS
toggle would have carried.

**Validate by parsing, never by status code.** BambooHR answers an unknown token with **HTTP 200
and its own marketing page** rather than a 404, and it will not be the only one. A board is
healthy when its response parses as the expected shape and yields rows; anything else is a dead
token, named on the company row and in run history.

**Isolate per company, not just per source.** The pipeline isolates failures per *source*, and
this source is twenty-five boards behind one entry. A 404 on one dead token must not cost the
other twenty-four: wrap each company and emit an event naming the one that failed. Tokens rot —
`~/git/Job-Tracker-main` ships a 25-company list of exactly this shape and several of its slugs
are already dead. Ship a starter list as an importable example so the feature demonstrates itself
before the user has added anything, and verify every token in it.

**Interrupts, same contract as the other scrapers.** Every `get()` takes `interrupt=ctx.interrupt`
and raises `PauseRequested`; collect into a list declared outside the loop and return what was
gathered, because `fetch()` only hands its jobs to the pipeline on return and resume does not
re-scrape. `linkedin.py:162` carries the comment explaining why letting `PauseRequested` escape
bins the whole scrape.

**Do not reuse `clean_description()` unmodified — the ordering is wrong here.** It strips tags
*then* unescapes, which is right for RemoteOK. Greenhouse `content` arrives entity-escaped
(`&lt;h2&gt;&lt;strong&gt;Who we are&lt;/strong&gt;&lt;/h2&gt;`), so that order finds no real
tags, unescapes afterwards, and leaves literal `<h2>` markup in the description — verified
against the live payload:

```
strip-then-unescape → '<h2><strong>Who we are </strong></h2>\n<h3>About Stripe...'
unescape-then-strip → 'Who we are \nAbout Stripe\nStripe is a financial...'
```

Every surviving tag is paid for twice, in the scoring prompt and in the cover letter prompt.
Promote the helper to `scrapers/base.py` with the order as a parameter — one function, two
orderings, chosen per source. Ashby needs neither: `descriptionPlain` is already plain.

### The intake gate is the phase's real constraint

Volume is not a side effect of these sources, it *is* them. Himalayas alone offers 102,388 jobs;
twenty-five ATS boards are thousands more, because a company posts its warehouse and sales roles
on the same board as its engineering ones. At `SCORING_DELAY_SECONDS` per job every one of those
costs a wait and an LLM call, so an ungated first run queues more than a year of nights and fills
the jobs table with roles the user would never have opened.

**A budget, then a ceiling.** `INTAKE_MAX_PER_RUN` (default 200) is the number of jobs a run may
queue in total, and `INTAKE_MAX_PER_SOURCE` (default 80) stops one feed eating the whole budget.
Both are Phase 1 settings, edited in Settings → Sources. The budget is the knob that matters
because it is the one that maps to wall-clock: show the arithmetic live beside the field —
*"200 jobs × 20s ≈ 67 minutes"* — so changing either number shows its cost rather than making the
user do the multiplication.

**Feeds are filtered; companies are not.** A feed carries the whole world, so nothing from one
reaches `pending_jobs` without passing a cheap deterministic relevance check: the scoring
`remoteok.py` already does — `TITLE_BONUS` / `SKILL_POINTS` / `MIN_SCORE` against the CV keywords
the run already extracted. Note that filter currently reads RemoteOK's own item shape, so
promoting it to `scrapers/base.py` as `prefilter(jobs, keywords)` is a rewrite against
`PendingJobRequest`, not a move. No LLM anywhere in it: the whole point is that it costs nothing.

A company row is different. The user named that company, so relevance is already established and
a sideways role their CV keywords do not match is exactly the job they would want to see. Company
jobs skip the filter — and stay under the ceiling, because an unfiltered board is still 600 roles
including the warehouse ones.

**Where it runs.** In the pipeline, between `fetch()` and `save_pending_job()`, never inside
intake. `save_pending_job()` is the single write path and is also used by
`POST /api/jobs/pending`, where a job the user added by hand must never be silently dropped for
looking irrelevant. Sources stay free of persistence, which is the existing contract.

**Order matters, because first wins.** Companies and boards are walked before feeds inside a run,
so when the same role exists in both places the ATS copy is the one that lands: full description,
real application link, no syndication truncation.

**Emit what was dropped.** Each source reports offered / kept / dropped, and the run reports
budget used. A cap set too tight and a dead source look identical until those numbers sit side by
side.

**A high-volume feed is also a paging decision.** Himalayas pages by cursor and will happily serve
everything; the source stops at the first page that yields nothing the filter keeps, or at its
ceiling, whichever comes first. Do not walk 102k rows to discard 101,950 of them.

### Companies as a source

`starred_companies` already carries `careers_url` and nothing reads it. Turn the company list into
the one source that fetches per company — whether by ATS API or by reading the page.

**Two independent facts per row, and they are not the same fact.**

| Column | Means | Reads |
|---|---|---|
| `starred` | *I want to work here* | Jobs filters today; the score in Phase 3 |
| `in_workflow` | *Scrape this company every run* | This source |

A row can be scraped without being starred — a competitor's board you watch but do not want
floating to the top of your list — and starred without being scraped, which is every row that
exists today. Existing rows migrate as `starred = true, in_workflow = false`, so nothing starts
scraping because of an upgrade.

**Two controls per row in the Companies tab, also independent.**

| Control | Writes | Effect |
|---|---|---|
| **In workflow** switch | `in_workflow` | the nightly run fetches this company |
| **Scrape now** button | nothing persistent | fetches this one company immediately and queues what it finds |

Neither implies the other. Scrape now works with the switch off — that is the point of it, trying
a careers URL before committing it to every run — and a company in the workflow is still
scrapeable on demand between runs. The `companies` row in `sources` gates the nightly walk;
`in_workflow` picks the rows inside it; **Scrape now bypasses both**, because it is an explicit
action on a named company.

**The row carries its own verdict.** Alongside `careers_url`: `in_workflow` (default false),
`starred` (default true), `ats` and `ats_token` (detected, nullable), `fetch_method`, and
`last_scraped_at` / `last_job_count`. `fetch_method` is what the row renders and what the
in-workflow switch reads before it lets itself be turned on:

| `fetch_method` | Row says | Switch |
|---|---|---|
| `unknown` | "Checking this page…" | unavailable |
| `ats` | "Greenhouse board detected" | available |
| `page` | "Reading the page directly — breaks when they redesign" | available |
| `unreadable` | "We cannot read jobs from this page", plus the reason | **refuses to turn on** |

A company that silently returns zero every night while looking healthy is the exact failure this
phase exists to prevent, and a switch that can be turned on for `unreadable` is a switch that
lies.

**Detection is a sniff, and it runs in the background.** Saving a careers URL must not block on
fetching a third-party page, so the write returns immediately with `fetch_method = "unknown"` and
the sniff lands a moment later. Two passes, cheapest first. URL shape catches the companies that
link straight at their board:

| URL shape | Resolves to |
|---|---|
| `boards.greenhouse.io/{token}`, `job-boards.greenhouse.io/{token}` | Greenhouse |
| `jobs.lever.co/{token}` | Lever |
| `jobs.ashbyhq.com/{token}` | Ashby |
| `{company}.recruitee.com`, `apply.workable.com/{token}` | Recruitee / Workable, once those parsers land |

When that fails, fetch the page once and look for what is behind it — `careers.acme.com` is very
often a Greenhouse board wearing a company domain:

| Fingerprint in the HTML | What it proves |
|---|---|
| link or iframe to a known board host | ATS behind a custom domain — the token is in that URL |
| `grnhse_app`, the Lever widget, Ashby `embed.js` | board embedded in the page |
| `<script type="application/ld+json">` with `@type: JobPosting` | no ATS, but structured job data to parse |

A hit upgrades the company from page-reading to a one-request, full-description fetch, so the
sniff pays for itself the first time it fires.

**The page path stops at deterministic rungs.** JSON-LD first, then an obvious listing structure,
then `unreadable`. The page is **never** handed to an LLM for extraction: that rung costs a call
per page per run and is the only one that can invent a job that was never posted — which then
costs a scoring call, a cover letter and a slot in the table, and looks exactly like a real job.
Cache by content hash so an unchanged page costs nothing on the next run. A page that yields zero
twice running moves to `unreadable` and turns its own switch off rather than being retried
forever.

Worked example, measured rather than assumed — `https://www.google.com/about/careers/applications/`
returns 1.13 MB of HTML with **no** board-host link, **no** embed script, **no** parseable JSON-LD
and no job text at all: the listings render client-side at `/jobs/results/`. Google runs its own
in-house ATS, which is a normal thing for a large employer to do, so the answer is to say
`unreadable` and move on. The company stays starred, still filters and still scores; its roles
arrive through Himalayas or LinkedIn instead.

**Check `robots.txt` before any page fetch, and cache the verdict per host.** It is part of the
`unreadable` verdict: Google's disallows the paginated results outright —

```
Disallow: /about/careers/applications/jobs/results?page=
```

— so even a page that could be read is one we are asked not to walk. A disallowed listing path is
`unreadable`, stated as such on the row, not a thing to engineer around. This does not apply to
the ATS APIs, which are documented public endpoints meant to be called.

**One fetch function, two callers.** The `Source` protocol takes a `RunContext` and Scrape now has
no run, so write the unit as
`fetch_company(company, interrupt=None) -> list[PendingJobRequest]`. The `companies` source wraps
it in the per-row loop; the endpoint calls it directly.

**`POST /api/companies/{id}/scrape`** runs `fetch_company` and writes through
`save_pending_job()`, so the blocklist, `seen_jobs` and the fingerprint check all apply unchanged
— including a company that is both in the list and blocked, which intake resolves by blocking. It
returns the counts it got back: `{"queued": n, "already_seen": n, "blocked": n}`. It opens no
`workflow_runs` row: it is not a run, it writes no run state, and the pipeline stays the only
writer of that table.

**Be honest about what "now" means.** Scrape now fills `pending_jobs`; the jobs table is written
by the scorer, so nothing appears under Jobs until a run drains the queue. Say "queued 7 jobs —
they are scored on the next run" and put the trigger next to it, rather than letting the button
look broken for a night.

**Identity.** An ATS-resolved row uses the ATS id scheme above, so the same posting reached
through this source and through a board token elsewhere is one job. The page path has no stable
id: use `company_{name}_{sha1(applylink)}` and lean on the fingerprint for the rest — a careers
page that renumbers its links is exactly what fingerprinting is for.

### Cross-source duplicates

Today identity is the source's own id, prefixed: `linkedin_4123…`, `remoteok_98765`. Two
sources carrying the same posting are two `seen_jobs` rows, two queue entries, two LLM calls
and two cards. Nothing deduplicates anywhere.

This is survivable with two sources whose catalogues barely overlap. It stops being
survivable the moment the ATS boards land, because **the ATS posting and the LinkedIn
posting are the same role by construction** — LinkedIn is syndicating what the ATS published.
Ship the dedupe with the sources, not after them.

**Add a fingerprint alongside the id.** Keep `id` as the primary key — it is exact, free and
correct within a source. Add an indexed `fingerprint` column to `seen_jobs`:

```
fingerprint = sha256(normalise(company) + "::" + normalise(title) + "::" + normalise(location))
```

`save_pending_job()` is already the single write path into `pending_jobs`, so it is the only
place that has to check both: known `id` → `already_seen` as now; known `fingerprint` →
`already_seen` as well.

**Normalisation is the whole game.** Lowercase, strip punctuation, collapse whitespace, drop
legal suffixes (`Inc`, `Inc.`, `Ltd`, `LLC`, `GmbH`, `Corp`, `Co`) and strip the LinkedIn
title decorations that the ATS does not carry. Keep the raw name for display; match on the
normalised one. The blocklist gets this for free and needs it — it is exact-match today, so
`Acme` and `Acme Inc.` are two different companies and blocking one leaves the other
arriving nightly.

**First wins, and the order is the design.** The ATS copy is the one worth keeping — its
description is the original rather than a truncated syndication, and its `applylink` is the
application form instead of a redirect, which is what `ROADMAP.md:122`'s ATS form POST would
later build on. Rather than ranking sources and letting a later arrival *replace* a queued
duplicate — which needs a rank column, fingerprints on two more tables, and delete-and-reinsert
inside a function that already commits — walk companies and boards **before** feeds inside a run.
The good copy then arrives first and the feed copy is the one dropped. Revisit only if truncated
syndicated descriptions actually show up in the table; the per-source health numbers are what
would show it.

**Accept one collision.** Two genuinely different requisitions with the same title at the
same company and location collapse into one. That is the right trade: a duplicated card is a
daily annoyance across every source, a lost near-identical req is rare and costs one posting
you can still reach from the company's board.

**Backfill, and the part of it that is impossible.** `filtered_jobs` and `pending_jobs` carry
company, title and location, so the migration computes their fingerprints directly. **`seen_jobs`
cannot be backfilled**: it is `(id, seen_at)` and nothing else, so a job that was scored and
drained, or blocked, leaves no material to fingerprint from. The migration therefore fills
`seen_jobs.fingerprint` only for ids that still exist in `filtered_jobs` or `pending_jobs`, and
leaves the rest null — a null fingerprint never matches, so those rows keep working on `id` alone
exactly as they do today. The consequence is bounded and worth stating plainly: for jobs already
scored and drained before the upgrade, a duplicate from a newly added source can still arrive
once. It costs one scoring call each, one time.

### Per-source health

With eight sources a silently dead one is invisible. `run_events` already records per-source
counts — surface them beside run history, with the per-board detail the ATS sources emit, and the
offered / kept / dropped triple the intake gate produces. A source whose kept count is zero while
its offered count is healthy is a filter that is too tight, which looks identical to a dead source
until the numbers are side by side.

The `companies` source reports per company rather than per source: fetch method, last count, last
scraped. That readout is what a per-ATS toggle would have bought and more, which is why decision 1
could drop the per-ATS rows without losing anything. A row that has moved to `unreadable` says so
there rather than contributing a silent zero to the source total.

### Done when

Himalayas and We Work Remotely are feeds you can switch off, the company list fetches Greenhouse,
Lever and Ashby boards by detection rather than by configuration, a company with a careers URL can
be put in the workflow or scraped on demand independently of each other and of the star, the same
role from two sources arrives once, a dead feed or a dead board is visible in run history rather
than silent, and adding the next feed is a new module plus a row.

And the gate holds: a run against a 102k-job feed queues tens of jobs rather than thousands, the
run history says how many each source offered, kept and dropped, and no job reaches the scorer
that a free title-and-skills check would have rejected.

And nothing lies about what it can do: a careers page we cannot read says so when it is pasted,
its switch refuses to turn on, and `robots.txt` is checked before any page fetch — so a company in
the workflow is a company that actually produces jobs.

---

## Phase 3 — The feedback loop

### Start by measuring, not building

Current state is `user_status: {'new': 14}` — **zero labels** — with 73 jobs still unscored.
Before any loop:

1. **Drain the queue.** The bottleneck is throughput, not scoring quality.
2. **Add one chart: apply-rate by score band.** A group-by over data you already store,
   answering the question that decides everything else: *is the score predictive at all?*
   If the 80+ and 60–70 bands convert identically, the scorer is noise and no feedback will
   fix it — you would fix the prompt instead.

Skipping to model-shaped work before this is the classic mistake.

### Two gestures, two different meanings

`user_status` tracks *the job*. A thumb rates *the recommendation*. They decouple: a perfect
match you skip because you already applied twice at that company is `wont_apply` with a
**thumbs up**. Treating that as a negative teaches the scorer to stop finding good jobs.

| Gesture | Cost to user | Volume | Signal |
|---|---|---|---|
| Dismiss → `wont_apply` | free, declutters the list | high | noisy negative |
| Thumb + reason | one deliberate tap | low | clean verdict on the score |

Keep both. The free one gives volume, the deliberate one gives truth.

**Make the negative free.** Zero labels today is a design problem, not a discipline problem:
marking a job costs effort and returns nothing. Dismissal works because the user already
wants a shorter list — the label is a byproduct.

**Give thumbs-down teeth.** Offer **Block company** inline. The blocklist is the one loop
already in daily use, because it visibly changes the next run.

### Why thumbs specifically

It is the only affordance that reaches **below the cutoff**. You cannot mark a `not_fit` job
`applied` — you never saw it. But you can thumb it: *"this scored 45 and deserved better."*
Those `not_fit` rows already carry their scores and are unreachable by every other signal.
Without them you only ever learn about the region you already accept, and the loop narrows
your search over time. Keep a deliberate trickle of below-cutoff jobs visible for exactly
this reason.

### Capture the reason

A bare thumb loses both magnitude and cause. A one-tap chip — *too senior / too junior /
wrong stack / location / company* — turns a scalar into an instruction you can read. Five
"too senior" in a row is a concrete change to the experience gate in the prompt, which is
inspectable in a way a learned weight is not.

It pairs with the evidence block already on the job card: the panel states which CV skills
matched, so a thumbs-down there records *which skills were present when it was rejected* —
per-skill signal, not just per-job.

### Storage and use

Mirror `job_status_history`: a table keyed by job id with verdict, reason and timestamp, so
history is preserved and taste drift is visible.

Then, by label count:

| Labels | What becomes possible |
|---|---|
| ~10–20 | Few-shot examples in the scoring prompt — the only technique worth building early |
| ~50 | Boost/damp CV keyword weights in `match_evidence.py` |
| ~150, ≥30 positive | Calibration: score → P(apply), so the cutoff becomes a probability |
| thousands | Fine-tuning — not this project |

Starred companies get their second set of teeth here. Phase 2 makes a star scrape the
company; this phase makes it weigh the score — a star should raise it or bypass the cutoff,
so the two halves of "I want to work here" both do something.

### Done when

Dismiss and thumb are one click each, apply-rate by band is on the Analytics page, and the
scoring prompt carries examples drawn from real verdicts.

---

## Phase 4 — Freelancing

The largest phase, because it is the only one where the **domain model differs**. Treat that
as the main risk, not the scraping.

### What does not carry over

| Employment | Freelance |
|---|---|
| Apply once, wait | Submit a proposal, often paying a platform credit |
| Salary, sometimes absent | Hourly rate or fixed budget, nearly always present |
| Fit = skills + seniority | Fit = skills + budget + competition + client history |
| Cover letter | Proposal — shorter, more specific, priced |
| `applied → interview → offer` | `proposal → shortlisted → interview → hired` |

`filtered_jobs.user_status` cannot absorb this. Either add a `job_kind` discriminator with a
separate status vocabulary, or keep freelance work in its own table. **Prefer the
discriminator** — Analytics, filters, Companies and export already work over one table, and
forking that doubles every future change.

Signals with no column today: budget, client spend history, client rating, number of
existing proposals. The last is the strongest predictor of whether bidding is worth it, and
has no equivalent in the employment flow.

### Sources

- **Freelancer.com** — public REST API with a key. Best first target; prove the data model
  here.
- **Upwork** — official GraphQL API, but requires an approved application and OAuth2.
  Approval is not guaranteed and scraping it is both against ToS and well defended. Treat as
  a second step gated on approval, not a launch requirement.
- **Wellfound, Contra, contract-filtered remote boards** — more value per unit of effort
  than Upwork.

### Scoring differs

The existing prompt scores CV-to-description fit. A proposal needs the CV, the description
**and** the budget, and should decline to bid when the rate is below a floor or the proposal
count is already high. That is a second prompt and a second parser in
`services/scoring.py`, not a parameter change.

### Dashboard

A separate top-level section rather than a filter on Jobs. The columns differ (budget,
proposals, client rating), the funnel differs, the actions differ. Reuse `jobs_list.py` and
the job panel as components; do not reuse the Jobs page.

### Done when

Freelance listings arrive from at least one platform, are scored with a budget-aware prompt,
and have their own section with a proposal-shaped pipeline.

---

## Sequencing

```
Phase 1  settings + notifications + source toggles
   |
   +--> Phase 2  ATS sources + cross-source dedupe
           |
           +--> Phase 3  feedback loop

Phase 4  freelancing   (independent, largest, last)
```

Phase 1 first is what makes Phase 2 cheap. The ATS boards need a per-board list, a per-source
toggle and a place to show per-board health; all three are settings surfaces, and building
them against `.env` means building them twice. The same argument retires the old ordering
argument about n8n — that migration is done, and the reason it went first still holds for
configuration now.

Phase 3 can start earlier than its position suggests — it is dashboard and API work that
barely touches the pipeline. It sits after Phase 2 only because more sources means more
volume means labels accumulate faster.

Phase 4 depends on nothing and can be deferred indefinitely.

## Cross-cutting

- **Company-name normalisation** — forced by Phase 2's dedupe, needed by Phase 3's
  per-company signal, and already owed to the blocklist, which is exact-match today. One
  helper, used by intake, the blocklist and starred companies alike.
- **Secret handling** — Phase 1 introduces the masked read path and the `redact_secrets()`
  pattern for webhook-shaped credentials. Every later phase that adds one (a Freelancer.com
  API key in Phase 4) reuses it rather than inventing a second convention.
- **Queue volume** — Phase 1 makes `SCORING_DELAY_SECONDS` editable, Phase 2 multiplies intake
  by orders of magnitude. The answer is the intake gate: `INTAKE_MAX_PER_RUN` (200) over
  `INTAKE_MAX_PER_SOURCE` (80), with a deterministic `prefilter()` on feeds and none on companies,
  in the pipeline between fetch and save. Decided in Phase 2, not discovered on the first run
  against a feed with six figures of jobs in it.
- **`run_events`** — already built, relied on by Phase 2's per-source and per-board health
  and Phase 3's measurement chart. Extend the schema, do not route around it:
  `RunContext.emit()` stays the only reporting path.
- **`ai_status` recompute on cutoff change** — Phase 1, re-check in Phase 3 when starred
  companies start influencing the score.
- **Test coverage** — `python-api/tests/` holds fifteen files. Extend as each phase lands
  rather than as a separate effort; the ATS parsers get recorded fixtures the way the
  LinkedIn and RemoteOK parsers did.
