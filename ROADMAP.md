# Find Me a Job — Roadmap

Two directions for the project, written after a full pass over the codebase.
Section 1 keeps it a self-hosted tool anyone can clone and run.
Section 2 is what it would take to run it as a paid online service.

---

## Shipped

Items from this roadmap that are now built. Details in the README.

| Was | Now |
|-----|-----|
| **Company blacklist** (was 1.2) | `blocked_companies` table mirroring starred. Enforced in the API at `POST /api/jobs/pending`, so every source gets it for free and a blocked company never costs an LLM call. Block from the job card, in bulk from the table, or in Companies → Blocked. |
| **Search config in the dashboard** (was 1.9) | Settings tab edits `params/*.txt` through `PUT /api/params/{name}`, with JSON validation that disables Save rather than writing a broken file. |
| **CV upload** (was 1.9) | Settings tab uploads `cv.docx`. The file is parsed before it overwrites the existing CV, so a corrupt upload cannot destroy a working one. |
| **"Run now" + Open n8n** (was 1.9) | Buttons in Settings. Run now posts to the main workflow's webhook; the workflow must be Active in n8n. |
| **Export + backup** | CSV/JSON export of the jobs table, and a one-click `jobs.db` snapshot via `VACUUM INTO` — consistent even while the stack is running. |
| **Run history** | `workflow_runs` records every run. The workflow reports start and finish; the API derives the scored/matched counts from what landed in the window. An abandoned run is marked failed instead of showing as running forever. |

**Also fixed along the way:** the Alembic chain could not build a database from nothing —
its first revision `ALTER`s tables that nothing creates any more, so a fresh clone
crash-looped on startup. New databases are now created from the models and stamped at
head, and the indexes are declared on the models so a fresh install and an upgraded one
produce identical schemas.

### Still open from the setup thread

- **`setup.sh`** (was 1.9) — an interactive first-run script that prompts for LLM
  provider/key, timezone, Telegram and email, writes `.env` at mode 600, copies the CV
  and offers to start the stack. Was built, then pulled; setup is manual for now
  (`cp .env.example .env`). To be revisited.

- **Prebuilt images on GHCR** so `docker compose up` pulls instead of building locally.
- **The last manual step**: the main workflow still has to be toggled Active in n8n once,
  because an imported workflow does not register its webhook until activated. Worth
  closing with an n8n REST call at startup or a first-run helper.

---

## Section 1 — Better as a self-hosted local project

### 1.1 The biggest single win: pull from ATS boards, not just job sites

Everything downstream of `pending_jobs` is source-agnostic — adding a source is one n8n
sub-workflow plus a new `website` value. That makes source coverage the cheapest lever
in the whole project.

The highest-value additions are not more scrapers, they are **applicant tracking system
(ATS) boards**, which expose free, unauthenticated, structured JSON and never rate-limit
or shadow-ban you the way LinkedIn scraping does:

| Source | Endpoint shape | Why it matters |
|--------|----------------|----------------|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | Huge coverage of tech companies, full description included |
| Lever | `api.lever.co/v0/postings/{company}?mode=json` | Clean JSON, includes structured lists |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{name}` | Growing fast among startups |
| Workable / Recruitee / SmartRecruiters | public board JSON per company | Long tail |
| Hacker News "Who is Hiring" | Algolia API over the monthly thread | Very high signal, low noise |
| WeWorkRemotely / Remotive | RSS / JSON | Same shape as the existing RemoteOK flow |

This pairs directly with the `starred_companies` table that already exists: it has a
`careers_url` column that nothing currently reads. Store the ATS slug there and the
system becomes **"watch my 40 target companies' career pages every day"** — which is how
people actually land jobs, and something no job board does well.

**Effort:** one sub-workflow per source. **Impact:** fresher listings, no ban risk, and
descriptions that are complete rather than truncated.

### 1.3 Cut LLM spend 50-70% with a pre-filter

Right now every scraped job costs a full LLM call (~1.7k-2.7k tokens) even when it is
obviously irrelevant. Two cheap gates before the expensive call:

1. **Hard filters** — salary floor, seniority mismatch, blacklisted company, required
   keywords absent, location/visa rules. Pure SQL/regex, zero cost.
2. **Embedding pre-filter** — embed the CV once, embed each job description, drop
   anything below a cosine threshold. `sqlite-vec` adds this as one extra table with no
   new service. Embeddings cost roughly 1/100th of a scoring call.

Add a **token/cost counter per run** in the dashboard so the saving is visible.

### 1.4 Deduplicate jobs across sources

The same posting on LinkedIn and RemoteOK is scored twice and shown twice, and companies
repost the same role monthly. Normalising `(company, title)` plus a fuzzy/embedding match
on the description would cut both noise and spend. The `seen_jobs` table already gives you
the hook.

### 1.5 Make the scoring explainable and self-correcting

A bare 0-100 number is hard to trust or tune.

- **Structured rubric output** — skills match / experience fit / location / comp as
  separate sub-scores, rendered as a small breakdown in the job card. Users immediately
  see *why* something scored 62.
- **Feedback loop** — a thumbs up/down on "was this actually a good match?" stored per
  job, with the last N disagreements injected into the prompt as few-shot examples. This
  is the cheapest personalisation available and it compounds over weeks.
- **Per-search scoring profiles** — someone hunting both "backend" and "data platform"
  roles needs two CVs and two rubrics, not one blended average.

### 1.6 Application assets, not just a cover letter

`application_document` currently holds one generated cover letter. Extend to:

- **Tailored CV** — LLM rewrites bullet points to mirror the job's language, exported as
  `.docx` (`python-docx` is already a dependency, so this is nearly free).
- **ATS keyword gap panel** — which required keywords appear in the job but not the CV.
  This is the single most requested feature in every job-search tool.
- **Answer bank** — a table of reusable answers (visa status, notice period, salary
  expectation, "why this company") that the LLM draws on to fill applications.

### 1.7 Auto-apply — be honest about the three tiers

This is the headline feature people want, and it deserves a clear-eyed split:

| Tier | Mechanism | Verdict |
|------|-----------|---------|
| **1. Email apply** | SMTP with CV attached | Already built. Safe, reliable. |
| **2. ATS form POST** | Greenhouse/Lever/Ashby accept documented application submissions | **Best next step.** Deterministic, no browser, no ToS problem. |
| **3. Browser automation** | Playwright container driving LinkedIn Easy Apply | Works, but violates LinkedIn's ToS, risks a permanent account ban, and breaks on every UI change. |

For tier 3 the better product is **assisted apply**: open the posting with the answers
pre-staged (clipboard payload or a small userscript) and let the human press submit. Nearly
all the time saving, none of the ban risk. Mass blind auto-apply also measurably *lowers*
response rates — volume is not the bottleneck, relevance is.

### 1.8 Turn the tracker into a real pipeline CRM

`job_status_history` already records every transition and nothing surfaces it beyond a
list. Build on it:

- **Follow-up reminders** — "applied 7 days ago, still no reply" → Telegram nudge.
- **Kanban board view** of the pipeline stages that already exist in the enum.
- **Interview scheduling fields** — date, round, interviewer, notes.
- **Funnel analytics** — response rate by source, by score band, by week. This answers
  "is my CV the problem or my targeting?" which is the question that actually matters.

### 1.10 Smaller wins worth doing

- **Browser extension / bookmarklet** — "save this job" from any site into the DB via the
  existing manual-add endpoint.
- **Ollama documented properly** — the fully-local, zero-API-cost path is a strong selling
  point for a self-hosted project and currently gets one table row.

---

## Section 2 — Turning it into a profitable online service

### 2.1 What already transfers

The architecture is better positioned than most side projects: FastAPI is cleanly
separated from the UI behind an HTTP boundary, the repository layer isolates all data
access, Alembic migrations exist, statuses are enums, and status history is already
tracked. The API could serve a different frontend tomorrow.

### 2.2 What has to be rebuilt

| Area | Today | Needed |
|------|-------|--------|
| Tenancy | Single user, implicit | `user_id` on every table, tenant scoping in every repository method |
| Database | SQLite, single file | Postgres, connection pooling, read replica eventually |
| Frontend | Streamlit | Streamlit has no auth model and re-runs the whole script per interaction. Replace with React/Next.js against the existing API |
| Orchestration | n8n, one instance | n8n-per-user does not scale. Celery/Arq + Redis, or Temporal for durable retries |
| Secrets | `.env` file | Per-user encrypted credential storage (their SMTP, their API keys) |
| Config | Text files on disk | Database-backed, per user |

The Streamlit → React migration and multi-tenancy are the two large items. Everything
else is incremental.

### 2.3 The hard problem: where the jobs come from

This is the part that decides whether the business is viable, and it is not a
technical problem.

- **Scraping LinkedIn commercially is not a viable foundation.** Datacenter IPs get
  blocked within hours, it violates their terms, and the litigation history around
  scraping (hiQ v. LinkedIn and its aftermath) makes it a real risk once you are charging
  money and visible.
- **What is viable:** ATS boards (§1.1) as the primary corpus — they are public,
  structured, and intended to be read. Supplement with licensed aggregator feeds (Adzuna,
  JSearch, Coresignal, Bright Data). Budget for this: data licensing becomes a genuine
  COGS line, not an afterthought.
- Being **ATS-first is also a product advantage**, not just a legal one: postings are
  fresher and more complete than aggregator copies, and you avoid the ghost-job noise
  that makes aggregators frustrating.

### 2.4 Unit economics — the thing that will decide profitability

LLM cost is the dominant variable cost and it scales with users × jobs, which is exactly
the wrong shape.

Rough shape: 200 jobs/day/user at ~2.5k tokens ≈ 500k tokens/day/user. At a few dollars
per million tokens that is meaningful per user per month before you have paid for
anything else.

The structural fix: **the same job is scored for many users.** Split the work:

1. **Per-job, done once, shared across all users** — parse, extract requirements, extract
   salary, embed. Cache it.
2. **Per-user** — only the CV-to-job match step, which is far smaller.

Combined with the embedding pre-filter and tiered models (cheap model to filter, strong
model only for cover letters on jobs the user actually wants), this is the difference
between a viable margin and a business that loses money per user. Enforce per-plan quotas
regardless.

### 2.5 Pricing, and the churn problem nobody mentions

A reasonable ladder: **Free** (one search, capped matches/day, no cover letters) →
**Pro ~$9-15/mo** (unlimited searches, cover letters, CV tailoring, auto-apply) →
**Power ~$29/mo** (many profiles, priority runs, API access).

The uncomfortable truth: **job hunting is inherently churn-y — your best outcome is the
user leaving.** Successful users cancel within 2-3 months. This breaks the usual SaaS
model and needs a deliberate answer:

- Sell **time-boxed packs** ("90-day job search sprint") rather than fighting for annual
  subscriptions.
- Build a **referral loop** — satisfied users who just landed a job are your best channel.
- Consider an adjacent, retaining audience: **career coaches and bootcamps** managing many
  candidates have real retention, or a **passive mode** ("keep watching, ping me if
  something exceptional appears") priced low for people not actively looking.

### 2.6 Compliance — non-optional, and larger than it looks

- **GDPR/CCPA**: CVs are personal data and often reveal special-category data
  (health, ethnicity, religion). You need a DPA, deletion/export flows, an EU hosting
  option, encryption at rest, and a published subprocessor list. **Your LLM provider is a
  subprocessor** — you need a zero-retention agreement with them before you send a single
  customer CV.
- **Email sending**: if you send applications from your own domain you will be
  blacklisted quickly — bulk applications look like bulk unsolicited mail. Send through
  **the user's own mailbox via Gmail/Outlook OAuth**. This is better for deliverability,
  better for the user (replies land in their inbox), and moves the compliance burden.
- **EU AI Act**: automated evaluation of *candidates for employers* is a high-risk use
  case. Your product scores *jobs for a candidate*, which likely keeps you outside
  Annex III — but that boundary disappears the moment you sell to recruiters. Make that a
  conscious product decision, not an accident. NYC Local Law 144 points the same way.
- **ToS exposure**: automating logins to third-party sites on a user's behalf is the
  legally weakest part of any auto-apply feature.

### 2.7 Engineering gaps before charging anyone

The project currently has **no tests at all** — that is the first thing to fix, because
everything below assumes a safety net.

- Tests (unit + API integration) and CI on every PR
- Error tracking (Sentry), structured JSON logging, metrics/tracing
- Rate limiting and abuse protection on every endpoint
- Automated backups with a *tested* restore path
- Staging environment, zero-downtime migration policy
- Billing (Stripe) with plan enforcement and dunning
- Admin panel — impersonation, quota overrides, refunds
- Product analytics (PostHog), support tooling
- Terms of Service, Privacy Policy, DPA, status page

### 2.8 Differentiation

The space is crowded: Simplify, Teal, Huntr, JobScan, Sonara, LazyApply. Volume-based
auto-apply is commoditised and has a poor reputation. The defensible angles:

1. **Explainable scoring** — show the rubric, not just a number. Nobody does this well.
2. **ATS-first corpus** — fresher, complete, fewer ghost jobs than any aggregator.
3. **Quality over volume** — 5 excellent tailored applications beat 200 blind ones, and
   the data supports saying so out loud.
4. **Open-core** — the self-hosted version stays free and is the top-of-funnel and the
   trust signal. Charge for the hosted convenience, not for the capability.

Go to market through the repository itself: the OSS project is the marketing channel.

### 2.9 Suggested order

1. Tests + CI (nothing else is safe without this)
2. ATS-board sources — improves the self-hosted product *and* is the SaaS foundation
3. Postgres + `user_id` tenancy
4. Auth + React frontend
5. Shared per-job processing and the embedding pre-filter (the margin fix)
6. Billing, quotas, compliance
7. Auto-apply via ATS form POST

Steps 1 and 2 pay off immediately for the self-hosted project, so the two roadmaps
share a runway rather than forking on day one.
