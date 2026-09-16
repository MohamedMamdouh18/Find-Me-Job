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

### Be honest about which are realistic

**Easy and reliable — do these first**

| Source | Shape |
|---|---|
| Greenhouse / Lever / Ashby | per-company public board JSON, full descriptions, never shadow-ban |
| We Work Remotely | RSS feed, no auth, no rate limit |
| Remotive | public JSON API |
| Hacker News "Who is Hiring" | Algolia API over the monthly thread; very high signal |

**Hard, and likely to stay broken**

- **Indeed** — killed its public API and sits behind aggressive bot detection. Reliable
  scraping needs a headless browser and rotating egress. Out of proportion to this project.
- **Glassdoor** — same posture, and its real value is reviews and salary rather than
  listings you cannot get elsewhere.

Recommend dropping both from scope, or attempting them only after everything above ships.
LinkedIn is already the most fragile source; two more of the same kind multiply maintenance
without multiplying coverage.

### The ATS boards are the phase

Greenhouse, Lever and Ashby are the strongest addition in the whole plan, and the reason is
not coverage — it is shape. They are documented JSON APIs with no auth, no rate limit worth
the name, and no bot detection, serving the companies you actually want *first*, because the
ATS is where the posting is created before it is syndicated anywhere else.

The decisive detail: **Greenhouse returns full descriptions in the list call.** One request
per company for every open role and its body. LinkedIn costs one request per search page
plus one per job page plus backoff, and can ban the egress IP; twenty-five ATS boards is
twenty-five requests and cannot.

**Endpoints**

| ATS | URL | List path | Description field |
|---|---|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `jobs[]` | `content` — HTML, entity-escaped |
| Lever | `https://api.lever.co/v0/postings/{token}?mode=json&limit=100` | top-level array | `descriptionPlain` plus `lists[]` |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{token}` | `jobPostingGroups[].jobPostings[]` | `descriptionPlain` |

**Field mapping to `PendingJobRequest`**

| Field | Greenhouse | Lever | Ashby |
|---|---|---|---|
| `id` | `greenhouse_{token}_{id}` | `lever_{token}_{id}` | `ashby_{token}_{id}` |
| `title` | `title` | `text` | `title` |
| `company` | board label | board label | board label |
| `location` | `location.name` | `categories.location` | `jobLocations[].name`, joined |
| `applylink` | `absolute_url` | `hostedUrl` | `https://jobs.ashbyhq.com/{token}/{id}` |
| `description` | `content` | `descriptionPlain` | `descriptionPlain` |
| `website` | `Greenhouse` | `Lever` | `Ashby` |

The company name comes from the stored board label, not from the payload — Greenhouse does
not reliably carry one, and Ashby's job URL has to be built from the board token. Deriving
either from a display name is how you get `jobs.ashbyhq.com/scaleai` for "Scale AI".

**Implementation.** One module, `scrapers/ats.py`, holding three parsers and a shared fetch
that loops over the board rows. Register three entries in `SOURCES` — `greenhouse`, `lever`,
`ashby` — each filtering the board list by its own ATS, so Phase 1's toggle and the
per-source health readout work per ATS rather than lumping all three together.

**Board tokens are a dashboard feature.** They live on `starred_companies` rather than in a
table of their own — see "Starred companies as a source" below, which is the same list under
another name. The Companies tab is where they are edited, beside starred and blocked
companies. Finding a token is reading it out of the careers URL — `jobs.lever.co/stripe` →
`stripe` — which is a thing a user can do and a thing that will need doing forever, so it
belongs in the UI rather than in a params file.

**Isolate per board, not just per source.** The pipeline isolates failures per *source*, and
an ATS source is twenty-five boards behind one entry. A 404 on one dead token must not cost
the other twenty-four; wrap each board and emit a source-level event naming the token that
failed. Tokens rot: `~/git/Job-Tracker-main` ships a 25-company list of exactly this shape
and several of its slugs are already dead. Copy the pattern, verify every token, and surface
a board returning zero jobs in run history — silent zero is the failure mode here, not an
exception.

**Interrupts, same contract as the other two scrapers.** Every `get()` takes
`interrupt=ctx.interrupt` and raises `PauseRequested`; collect into a list declared outside
the loop and return what was gathered, because `fetch()` only hands its jobs to the pipeline
on return and resume does not re-scrape. `linkedin.py:162` carries the comment explaining why
letting `PauseRequested` escape bins the whole scrape.

**Reuse `clean_description()`.** Greenhouse `content` is entity-escaped HTML, and
`remoteok.py` already strips tags *before* unescaping, which is the ordering that stops
`&lt;div&gt;` from becoming a real tag and eating the text after it. Promote that function to
`scrapers/base.py` rather than writing a second one.

**Expect a volume problem.** Twenty-five boards is thousands of open roles, and the scoring
loop runs at `SCORING_DELAY_SECONDS` per job — the first ATS run queues far more than a night
can drain, and every one of those jobs costs an LLM call. Either seed the board list small
and grow it, or gate intake on a cheap deterministic title check before `save_pending_job`.
This is a consequence of the source, not a separate feature: it has to be decided in this
phase.

### Starred companies as a source

Starring is a bookmark today: `starred_companies` already carries `careers_url`, and nothing
reads it. Turn it into a source — the user has already told you which companies they want,
and the careers page is where those companies post first.

**Two controls per company, independent of each other.** In the Companies tab, each starred
row gets:

| Control | Writes | Effect |
|---|---|---|
| **In workflow** switch | `starred_companies.in_workflow` | the nightly run scrapes this company's careers page |
| **Scrape now** button | nothing persistent | fetches that one page immediately and queues what it finds |

Neither implies the other. Scrape now works on a company with the switch off — that is the
point of it, trying a careers URL before committing it to every run — and a company in the
workflow is still scrapeable on demand between runs.

**The global switch is the Phase 1 source row, not a new key.** Register `starred` in
`SOURCES` and seed a `sources` row for it; Settings → Sources then already carries the
enable/disable switch for starred scraping as a whole, with the same shape as LinkedIn and
RemoteOK. Adding a second `STARRED_*` setting would mean two switches that can disagree.
Precedence is the obvious one: the source row gates the workflow walk, `in_workflow` picks
the rows inside it, and **Scrape now bypasses both** because it is an explicit user action on
a named company.

**Fold the board list into `starred_companies`.** This replaces the separate `job_boards`
table sketched above: one company list, one careers URL, one place in the UI. Add
`in_workflow` (default false), `ats` and `ats_token` (detected, nullable), `last_scraped_at`
and `last_job_count`. A company is starred, has a careers URL, and is optionally in the
workflow — three facts about one row, not two tables to keep in sync.

**Detect the ATS from the URL; fall back to generic.** Most careers pages are an ATS board
wearing a company domain, and that is where the reliability is:

| URL shape | Path |
|---|---|
| `boards.greenhouse.io/{token}`, `job-boards.greenhouse.io/{token}` | Greenhouse parser above |
| `jobs.lever.co/{token}` | Lever parser above |
| `jobs.ashbyhq.com/{token}` | Ashby parser above |
| anything else | generic fetch, best effort |

Detection runs on save and caches `ats` + `ats_token` on the row, so the Companies tab can
say *"Greenhouse board detected"* against a pasted URL — which is the difference between a
user trusting the field and a user guessing at it. When it resolves to an ATS, the scrape is
the phase's own parser and inherits its reliability for free.

**The generic path is best-effort and must be labelled as such.** An arbitrary careers page
is React-rendered as often as not, and a list page rarely carries descriptions, so a body
costs a second request per role. Keep it deterministic first — look for a JSON-LD
`JobPosting` block, then an obvious listing structure — and only then hand the stripped page
to the LLM for extraction. Cache by content hash so an unchanged page costs nothing on the
next run; that is what stops a nightly walk over thirty companies from becoming thirty LLM
calls a night for no new jobs. A page that yields zero jobs twice running is surfaced in the
row, not silently retried forever.

**One fetch function, two callers.** The `Source` protocol takes a `RunContext`, and Scrape
now has no run. Write the unit as `fetch_company(company, interrupt=None) -> list[PendingJobRequest]`
and let the `starred` source wrap it in the per-company loop while the endpoint calls it
directly. Same isolation rule as the ATS boards: one company raising costs that company only.

**`POST /api/starred/{id}/scrape`** runs `fetch_company` and writes through
`save_pending_job()`, so the blocklist, `seen_jobs` and the fingerprint check all apply
unchanged — including the case where a company is starred *and* blocked, which intake
resolves by blocking. It returns the counts it got back:
`{"queued": n, "already_seen": n, "blocked": n}`. It opens no `workflow_runs` row: it is not
a run, it writes no run state, and the pipeline stays the only writer of that table.

**Be honest in the UI about what "now" means.** Scrape now fills `pending_jobs`; the jobs
table is written by the scorer, so nothing appears under Jobs until a run drains the queue.
Say "queued 7 jobs — they are scored on the next run" and put the trigger next to it, rather
than letting the button look broken for a night.

**Identity.** ATS-resolved rows use the ATS id scheme above, so the same posting reached
through a starred company and through a board token is one job. The generic path has no
stable id: use `starred_{company}_{sha1(applylink)}`, and lean on the fingerprint for the
rest — a careers page that renumbers its links is exactly the case fingerprinting exists for.

**Interrupts and volume, same rules as everywhere else.** Every `get()` takes
`interrupt=ctx.interrupt`, collects into a list declared outside the loop, and returns what
it gathered. Starred companies are a small list by construction, which is what makes them
safe to walk nightly — if the list grows past a few dozen, the intake gate decided above
applies here too.

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

**Prefer the ATS row.** When the same fingerprint arrives from two sources, the one that
survives should be the ATS copy: its description is the original rather than a truncated
syndication, and its `applylink` is the application form instead of a redirect — which is
what `ROADMAP.md:122`'s ATS form POST would later build on. That means source preference is
a ranked list, and a later-arriving preferred source must be allowed to *replace* a queued
duplicate rather than be dropped by it.

**Accept one collision.** Two genuinely different requisitions with the same title at the
same company and location collapse into one. That is the right trade: a duplicated card is a
daily annoyance across every source, a lost near-identical req is rare and costs one posting
you can still reach from the company's board.

**Backfill.** `seen_jobs` and `filtered_jobs` already hold rows without fingerprints, so the
migration computes them for existing rows. Without that, every pre-existing job stays
invisible to the new check and the first run after the upgrade re-queues its duplicates
anyway.

### Per-source health

With eight sources a silently dead one is invisible. `run_events` already records per-source
counts — surface them beside run history, with the per-board detail the ATS sources emit.

### Done when

Five or more sources are toggleable, board tokens are editable from the dashboard, a starred
company with a careers URL can be put in the workflow or scraped on demand independently, the
same role from two sources arrives once, a dead source or a dead board is visible in run
history rather than silent, and adding the sixth source is a new module plus a row.

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
- **Queue volume** — Phase 1 makes `SCORING_DELAY_SECONDS` editable, Phase 2 multiplies
  intake by an order of magnitude. They interact: decide the intake gate in Phase 2 rather
  than discovering it on the first ATS run.
- **`run_events`** — already built, relied on by Phase 2's per-source and per-board health
  and Phase 3's measurement chart. Extend the schema, do not route around it:
  `RunContext.emit()` stays the only reporting path.
- **`ai_status` recompute on cutoff change** — Phase 1, re-check in Phase 3 when starred
  companies start influencing the score.
- **Test coverage** — `python-api/tests/` holds fifteen files. Extend as each phase lands
  rather than as a separate effort; the ATS parsers get recorded fixtures the way the
  LinkedIn and RemoteOK parsers did.
