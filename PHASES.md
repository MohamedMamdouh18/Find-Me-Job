# Find Me a Job — Next Five Phases

Sequenced plan written against the current codebase. Complements `ROADMAP.md`, which holds
the long-form option list; this file is the committed order of work.

Phase 1 replaces n8n with python services. Everything after it is written once, in one
language, instead of being built in n8n and migrated later — which is the main reason it
goes first rather than last.

---

## Phase 1 — Replace n8n with python services

**Goal.** Delete the n8n container. The scheduler, the scrapers, the scoring loop and the
notifications all run inside the existing `python-api` container, with logging good enough
to replace what n8n's execution view was giving you.

### Why this is first

The honest argument against doing it first is that it rewrites a working core and delivers
no user-visible feature. The argument for it is stronger: **every later phase touches the
workflows.** Settings needs a `Get Settings` node and eight expression rewrites. Source
toggles need an `If` per source. Freelancing needs whole new workflows. Doing the
migration last means building all of that twice.

There is also a reliability argument with evidence behind it:

- A run died on `connect ETIMEDOUT` because n8n's HTTP client will not fail over between a
  hostname's addresses. Python's socket layer does it automatically, for free.
- `Parse AI Response` corrupted every pretty-printed LLM response for months. It lived in
  a JS code node where no test could reach it. It was found by reading it.
- The live instance silently ran a three-month-old version of the workflows. When code is
  code, that failure mode does not exist.

### You are already most of the way there

Of the main workflow's 43 nodes, **19 are HTTP calls back into `python-api`**. Those become
ordinary function calls. Already built and reusable as-is:

| Exists today | Replaces |
|---|---|
| `BackgroundScheduler` + `CronTrigger` in `main.py` | Schedule Trigger |
| `WorkflowRunRepository.start/finish` | Start Run, Finish Run |
| `send_telegram()` in `shared.py` | both Telegram nodes |
| `EmailService` | Send Email |
| `_docx_text`, `CVKeywordsRepository` | Read CV, CV keyword storage |
| `PendingJob/SeenJob/FilteredJob` repositories | every DB node |
| `PARAMS_DIR` reads | Read Keywords Prompt, linkedin_searches |
| `shared.DASHBOARD_URL` | Get Dashboard URL — now just a variable |

The scheduler is already running `delete_old_jobs` on a cron trigger, and uvicorn runs a
single worker, so adding the pipeline job is two lines with no duplicate-fire risk.

### What has to be written

```
src/services/llm.py         OpenAI-compatible client (one place, all three call sites)
src/services/keywords.py    CV -> titles + skills
src/services/scoring.py     prompt, call, parse, band decision
src/services/emailing.py    detect address, generate, send   (wraps EmailService)
src/services/pipeline.py    the orchestrator
src/scrapers/base.py        Source protocol: fetch() -> list[PendingJobRequest]
src/scrapers/linkedin.py    port of the 17-node sub-workflow
src/scrapers/remoteok.py    port of the 8-node sub-workflow
```

New dependency: `beautifulsoup4` for the LinkedIn HTML parsing. `httpx` is already present.

**Port `repairJson` as-is.** The string-literal-aware control-character escaping in
`Parse AI Response` is correct and hard-won — translate it to python directly and bring the
eight test cases with it as the first unit test of the new scoring service.

### Logging — the part that replaces n8n's execution view

This is the one genuine loss from dropping n8n, so treat it as a feature, not an
afterthought. `python-api` currently has **no `getLogger` at all** — 13 bare
`print(..., flush=True)` calls. Greenfield.

**Two sinks.**

1. **stdlib logging to stdout**, one logger per module, `run_id` on every record via a
   `contextvars` filter so lines can be correlated without threading an argument through
   every function. `docker compose logs` becomes useful.

2. **A `run_events` table** — `run_id`, `ts`, `level`, `stage`, `message`, `context` JSON.
   This is what the dashboard reads, and it is what makes a failed run diagnosable a day
   later. Prune it with the existing `DELETE_OLD_JOBS_DAYS` sweep.

**Log the payload on failure, not just the exception.** The specific thing n8n gave you was
the ability to open a node and see the data it actually received. Reproduce it where it
matters:

- LLM parse failure → log the raw response body
- Scraper parse failure → log the raw HTML (truncated) and the URL
- HTTP failure → status, URL, attempt number

Without this the migration is a downgrade. With it, it is an upgrade, because logs persist
and are greppable while n8n's execution data expires.

**Stages worth an event each:** run start, CV unchanged/changed, keywords extracted, per
source (started, N found, N new, failed), queue depth, per job (scored, band, dropped),
email sent, run finished with counts.

### Orchestration concerns n8n was handling implicitly

- **Runs are long.** 73 queued jobs at the current 20s inter-call wait is ~25 minutes. The
  manual trigger must return immediately and run in the background — the same behaviour we
  already settled on when the webhook was switched to `onReceived`.
- **One run at a time.** Take an advisory lock, or check for a `running` row before
  starting. `WorkflowRunRepository` already has `_fail_stale_runs`, which assumes
  single-run semantics.
- **Graceful shutdown.** A container restart mid-run must mark the run failed rather than
  leaving it `running` until the 6-hour stale sweep.
- **Single worker.** The scheduler assumes one uvicorn process. If `--workers` is ever
  added, the schedule fires N times. Document it, or gate the scheduler on a DB lock.
- **Rate limiting** moves from `Wait2` into the LLM client, where it can be adaptive rather
  than a fixed 20 seconds.

### Cutover

1. Build the services alongside n8n, reachable at `POST /api/runs/trigger`, without
   removing anything.
2. Capture HTML fixtures from a real LinkedIn search and job page. The parse logic is the
   fiddliest thing being ported and the only part with no equivalent already in python —
   fixtures make it testable, which it never was inside n8n.
3. Run both against the same database on a small queue and compare `filtered_jobs` output.
4. Flip the schedule to APScheduler, leave the n8n container up but its workflow inactive.
5. After a week of clean runs, delete the n8n service from `docker-compose.yml`, the
   `workflows/` directory, `n8n/`, and `data/n8n` — reclaiming a 654 MB `n8n.db`.

Keep step 4 for at least a few runs. The rollback is re-activating one workflow.

### Done when

`docker-compose.yml` has three services instead of four; the schedule and the dashboard's
Run now both drive the python pipeline; a failed run names the stage that failed and
carries the payload that caused it; the LinkedIn and RemoteOK parsers have unit tests over
recorded fixtures.

---

## Phase 2 — Everything configurable from the dashboard

**Goal.** A user never opens `.env` after first boot.

Phase 1 removes most of the difficulty here. There is no `Get Settings` node, no `$env`
expressions, no import/publish/restart cycle — settings are read from the database at the
point of use, in process.

### Design

**Database.** A `settings` table — key, value, updated_at. Flat key/value rather than a
column per setting, so later phases add keys without a migration each time. Seed from the
current environment on first boot so an existing install keeps working untouched.

**API.** `GET /api/settings` returns one flat object; `PUT /api/settings` takes a partial
update. The pipeline reads settings at the start of each run, so a change applies to the
next run with no restart.

**Dashboard.** A Providers section in Settings. The LLM endpoint is a picker with presets
plus free text:

| Preset | URL |
|---|---|
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` |
| OpenAI | `https://api.openai.com/v1/chat/completions` |
| Anthropic | `https://api.anthropic.com/v1/chat/completions` |
| Groq / Together / OpenRouter | their OpenAI-compatible paths |
| Custom | free text |

Every call posts an OpenAI-shaped body, so the only hard requirement is an
OpenAI-compatible `/chat/completions` endpoint. Say that next to the Custom field — it is
the difference between "any provider" and "any provider that speaks this shape".

### In scope

`LLM_URL`, `LLM_MODEL`, `LLM_API_KEY`, `FILTERING_SCORE`, `DELETE_OLD_JOBS_DAYS`,
`AUTO_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_APP_PASSWORD`, `SENDER_NAME`,
`TELEGRAM_ID`, `TELEGRAM_BOT_TOKEN`.

`TELEGRAM_BOT_TOKEN` is included because Phase 1 already deleted the n8n Telegram nodes —
the token lives in `send_telegram()` and is a normal setting. This also closes the release
audit's hardcoded-credential finding, which currently breaks fresh deployments.

**`GENERIC_TIMEZONE` stays in `.env`.** APScheduler is constructed with it at startup and
the dashboard uses it as the container clock (`TZ`). Changing it at run time changes
neither. Say so in the UI rather than letting it look broken.

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

A switch per site in the dashboard. With n8n gone this is a `sources` table (`name`,
`label`, `enabled`) and one check in the orchestrator:

```python
for source in enabled_sources():
    ...
```

No `If` nodes, no workflow ids, no redeploy. Seed with `linkedin` and `remoteok`, both
enabled, so upgrade behaviour is unchanged.

The case worth testing deliberately: **every source disabled**. Scoring reads the queue
from the database rather than from the scrapers, so a run with zero scrapers must still
drain any backlog rather than exiting early.

### Done when

`.env` holds only `GENERIC_TIMEZONE`, the database path and the host ports. Changing the
LLM provider, key, model, cutoff, retention, email settings, Telegram target or enabled
sources from the dashboard changes the next run with no restart.

---

## Phase 3 — More sources

Everything downstream of `pending_jobs` is source-agnostic, so after Phases 1 and 2 a
source is exactly: one module implementing the `Source` protocol, one `website` value, one
row in `sources`. No workflow, no id, no redeploy.

### Be honest about which are realistic

**Easy and reliable — do these first**

| Source | Shape |
|---|---|
| We Work Remotely | RSS feed, no auth, no rate limit |
| Remotive | public JSON API |
| Hacker News "Who is Hiring" | Algolia API over the monthly thread; very high signal |
| Greenhouse / Lever / Ashby | per-company public board JSON, full descriptions, never shadow-ban |

The ATS boards are the strongest addition in the phase. Structured, free, unauthenticated,
and where the companies you actually want post *first*. Cost: maintaining a list of company
board tokens — which is itself a natural dashboard feature and pairs with starred
companies.

**Hard, and likely to stay broken**

- **Indeed** — killed its public API and sits behind aggressive bot detection. Reliable
  scraping needs a headless browser and rotating egress. Out of proportion to this project.
- **Glassdoor** — same posture, and its real value is reviews and salary rather than
  listings you cannot get elsewhere.

Recommend dropping both from scope, or attempting them only after everything above ships.
LinkedIn is already the most fragile source; two more of the same kind multiply maintenance
without multiplying coverage.

### Cross-source work this forces

- **Company-name normalisation.** No deduplication exists anywhere today. The same role from
  Greenhouse and LinkedIn arrives as two rows, and the blocklist is exact-match, so `Acme`
  and `Acme Inc.` are two different companies. Normalise on write, keep the raw name for
  display.
- **Per-source health.** With eight sources a silently dead one is invisible. Phase 1's
  `run_events` already records per-source counts — surface them beside run history.
- **Failure isolation.** One source's 429 must not fail the run. In python this is a
  `try/except` per source inside the loop, logged as a source-level event.

### Done when

Five or more sources are toggleable, a dead source is visible in run history rather than
silent, and adding the sixth is a new module plus a row.

---

## Phase 4 — The feedback loop

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

Starred companies should finally get teeth here too: today starring only filters a view
while blocking changes the pipeline. A star should raise the score or bypass the cutoff.

### Done when

Dismiss and thumb are one click each, apply-rate by band is on the Analytics page, and the
scoring prompt carries examples drawn from real verdicts.

---

## Phase 5 — Freelancing

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
Phase 1  n8n -> python + logging
   |
   +--> Phase 2  settings + source toggles
           |
           +--> Phase 3  more sources
                   |
                   +--> Phase 4  feedback loop

Phase 5  freelancing   (independent, largest, last)
```

Phase 1 first is what makes the rest cheap. Every subsequent phase would otherwise be built
against n8n and then migrated: Phase 2 needs a settings node and eight expression rewrites,
Phase 3 needs a gate per source, Phase 5 needs new workflows entirely. Migrating first means
each of those is written once.

Phase 4 can start earlier than its position suggests — it is dashboard and API work that
barely touches the pipeline. It sits after Phase 3 only because more sources means more
volume means labels accumulate faster.

Phase 5 depends on nothing and can be deferred indefinitely.

## Cross-cutting

- **Logging and `run_events`** — built in Phase 1, relied on by Phase 3's per-source health
  and Phase 4's measurement chart. Get the schema right early.
- **Company-name normalisation** — forced by Phase 3, needed by Phase 4's per-company
  signal. Do it in Phase 3.
- **`ai_status` recompute on cutoff change** — Phase 2, re-check in Phase 4 when starred
  companies start influencing the score.
- **Test coverage** — `python-api/tests/` exists with 6 tests. Phase 1 should roughly triple
  it, since the scrapers and parsers become testable for the first time. Extend as each
  phase lands rather than as a separate effort.
- **Manual activation step disappears** with n8n. A fresh install becomes
  `cp .env.example .env && docker compose up -d`, closing the last open setup item in
  `ROADMAP.md`.
