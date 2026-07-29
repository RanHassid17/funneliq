# FunnelIQ

Campaign-intelligence application for **Northbound Media**, a performance-marketing agency.
FunnelIQ turns two years of funnel data into decision-ready answers: which campaigns produce
long-lived customers, where leads fall out of the follow-up sequence, and how to allocate a
₪50,000 monthly ad budget.

**Live URL:** <https://funneliq-api-production.up.railway.app>
· [`/health`](https://funneliq-api-production.up.railway.app/health)
· [`/ready`](https://funneliq-api-production.up.railway.app/ready)
· [`/docs`](https://funneliq-api-production.up.railway.app/docs)

Open the live URL, create an account, and the dashboard answers all six work packages.

> **Build status: all 8 phases complete.** Data, models, auth, the dashboard and the CrewAI
> analyst are live. Phase 7 walked the requirements matrix end to end and fixed the three defects
> it found; Phase 8 is the documentation pass.
> [`PLAN.md`](PLAN.md) is the full roadmap and the record of every decision behind it — §12 holds
> the traceability matrix and the Phase 7 findings.
>
> Railway deploys from GitHub `master`, so every merge redeploys automatically. The service runs
> on a free trial plan and may cold-start after a period of inactivity — the first request can
> take a few seconds.

---

## The one thing to know about this dataset

**Each row is one advertising campaign, not one customer.**

`ad_budget` is campaign spend, the lead and follow-up columns are campaign counts, `ltv_months`
is the *average* lifetime of the customers a campaign produced, and `cumulative_profit` is the
*total* profit attributed to it. Every model, chart, label and recommendation in FunnelIQ is
therefore campaign-level.

FunnelIQ does **not** predict individual customer churn, next-best-action, or a person's referral
probability. Those need a customer-level table linked by `campaign_id`, which does not exist yet.
Presenting a campaign-level score as an individual probability would be a category error, so the
product refuses to do it.

## Architecture

```
Browser (index.html = login, dashboard.html)
  └─ supabase-js ── ANON KEY ONLY ──────────► Supabase Auth
  └─ fetch(Bearer JWT) ─────────────────────► FastAPI on Railway
                                                ├─ verifies the Supabase JWT server-side
                                                ├─ models/*.pkl → campaign predictions
                                                ├─ Supabase client (SERVICE KEY,
                                                │    server-side only) ──► Postgres + RLS
                                                └─ crew/ → CrewAI campaign analyst
```

The split that matters: the browser only ever holds the **public anon key**; the
**service-role key never leaves the server**. CI fails the build if a JWT-shaped string is
committed or if client code references the service-role key.

## Local setup

Requires Python 3.11+.

**macOS users: install OpenMP first.** XGBoost and LightGBM ship native libraries that link
against it, and macOS does not provide one — without this they fail at import with an opaque
`Library not loaded: @rpath/libomp.dylib`:

```bash
brew install libomp
```

```bash
git clone https://github.com/RanHassid17/funneliq.git
cd funneliq

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env               # fill in your own values; .env is gitignored

uvicorn funneliq.api.main:app --reload --app-dir src
```

Then:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","service":"funneliq","version":"0.1.0","commit":"unknown","uptime_seconds":1.2}
```

`commit` reports `RAILWAY_GIT_COMMIT_SHA` when deployed, so `/health` tells you *which revision*
is actually serving traffic rather than making you infer it from a deploy log.

## Data layer

```bash
# Profile the raw CSV -> reports/profile.json
PYTHONPATH=src python -m funneliq.data.profile

# Validate campaign invariants without touching the database
PYTHONPATH=src python -m funneliq.data.load_to_supabase --dry-run

# Load into Supabase (needs SUPABASE_SERVICE_ROLE_KEY; idempotent)
PYTHONPATH=src python -m funneliq.data.load_to_supabase
```

Apply `sql/schema.sql` then `sql/rls_policies.sql` in the Supabase SQL editor before the first
load. Both are idempotent.

Three findings from the data change how it may be modelled, and are worth reading before touching
the feature code — [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) has the detail:

- `customer_acquisition_cost` equals `floor(ad_budget / closed)` in every row, so it silently
  encodes the sales outcome. It is excluded from every pre-outcome model.
- `purchased` is not "a deal closed" — it is exactly `cumulative_profit > 0`. 155 campaigns closed
  deals and collected nothing.
- `closed + not_closed` equals `followup_5` in every row, which settles the close-rate denominator.

Assumptions that could not be settled from the data are tracked in
[`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md); metric definitions are in
[`docs/GLOSSARY.md`](docs/GLOSSARY.md).

## Dashboard

| Route | |
|---|---|
| `/` | Login screen — Supabase Auth, email + password |
| `/dashboard.html` | Panels for every work package |

The dashboard is plain HTML/CSS/JS with no build step. The browser holds **only** the public anon
key and the session JWT Supabase issued it; the API verifies that token server-side and holds the
service-role key. `/api/config` serves the public values at runtime so no key is ever committed —
and a test asserts the service-role key can never appear in that response.

A logged-out visitor is redirected before any panel renders, and sign-out clears the session.

## API

| Route | Auth | Purpose |
|---|---|---|
| `GET /health` | public | Liveness. Never touches Supabase |
| `GET /ready` | public | Readiness: config, database reachability, model artifacts |
| `GET /api/campaigns` | **session** | Campaigns read **live from Supabase** |
| `GET /api/campaigns/{id}` | **session** | One campaign with derived metrics |
| `GET /api/campaigns/compare?a=&b=` | **session** | Two campaigns side by side, with deltas |
| `POST /api/predict/ltv` | **session** | Package 2 — average customer lifetime |
| `POST /api/predict/upsell` | **session** | Package 3 — upsell likelihood |
| `POST /api/predict/referral-score` | **session** | Package 4 — 0–100 campaign score |
| `POST /api/predict/profit` | **session** | Package 6 — pre-launch profit |
| `POST /api/budget/simulate` | **session** | Package 6 — allocation strategies |
| `GET /api/funnel/dropout` | **session** | Package 5 — stage dropout + recommendation |
| `GET /api/models` | **session** | What is served, with each model's baseline comparison |
| `POST /api/ask` | **session** | Phase 6 — ask the CrewAI analyst a campaign question |
| `GET /api/ask/status` | **session** | Whether the analyst is configured, and its limits |

Every protected route returns **401** without a valid Supabase JWT. Interactive docs at `/docs`.

**`/health` and `/ready` are deliberately different.** Liveness must not depend on the database —
a health check that fails during a brief Supabase blip makes the platform restart a process that
was never broken. Readiness *does* check it, and reports each dependency separately, because "the
database is unreachable" and "the models were never trained" need different fixes.

**The LTV and profit endpoints serve the budget baseline, not the ensembles** — the honest
consequence of boosting failing to beat it. Each response names the model that answered it.

**Every prediction says whether it is extrapolation.** Each response carries `in_distribution`,
and when it is `false` an `out_of_range` list names the offending field beside the range actually
observed in training. Phase 7 found a zero-lead campaign coming back with a confident 33.66-month
lifetime, because the budget baseline reads only `ad_budget` and cannot notice a funnel that
reached nobody. The number is still returned — a campaign that spent its budget and got no leads
is a real thing — but it is returned labelled. Only fields the caller actually sent are checked,
so an ordinary pre-launch `{"ad_budget": 3000}` is not flagged for funnel counts it never
supplied. The analyst's `run_model` tool carries the same annotation, so an agent cannot quote a
figure the API marked unsupported.

## Models

```bash
# Train all four models, run the leakage smoke test -> reports/models.json, models/*
PYTHONPATH=src python -m funneliq.models.train

# Simulate the 50,000 monthly budget -> reports/budget_simulation.json
PYTHONPATH=src python -m funneliq.models.budget

# Ask whether tuning changes the LTV verdict (~5 min) -> reports/tuning_ltv.json
PYTHONPATH=src python -m funneliq.models.tuning
```

Trained artifacts are committed (636 KB) with a provenance card each — features, checkpoint, seed,
git SHA, row count, metrics and baseline comparison. A test asserts every committed card still
matches the current feature policy, so a policy change cannot silently leave a stale leaky model
in place.

**Two of the four models do not beat their naive baseline**, and
[`docs/MODEL_CARDS.md`](docs/MODEL_CARDS.md) says so per model rather than quoting the flattering
number. Findings and business recommendations are in [`REPORT.md`](REPORT.md).

## The AI analyst

```bash
# Draft a findings section from the committed reports (costs money)
PYTHONPATH=src python -m funneliq.crew.run --stage analysis

# Show what it would read and whether it can run — free
PYTHONPATH=src python -m funneliq.crew.run --stage analysis --dry-run
```

An **Analyst** agent with four tools drafts an answer; a **Reviewer** agent with *no* tools then
checks it. The reviewer is deliberately toolless: giving it tools would let it fetch a figure the
analyst never had and quietly repair the draft, when the question is whether *the analyst's*
answer was supported.

**It is optional and it is the only thing here that costs money per request.** Without
`ANTHROPIC_API_KEY`, `/api/ask` returns 503 with the reason, the dashboard hides the panel, and
everything else works. `funneliq.crew` therefore imports CrewAI *inside* functions rather than at
module scope — CrewAI drags in chromadb, onnxruntime and grpc, and if any of that fails to load on
the deployment image the right outcome is one broken endpoint, not a dead service. Phase 4 already
learned that lesson from `libgomp`.

Three brakes on spend: six iterations per agent and a usage cap per tool, ten requests per minute
per crew, and twenty questions per user per hour. The hourly limit is in-process, so with multiple
replicas the real ceiling is `replicas × 20`.

The tools take **structured parameters, never SQL and never a table name**. The crew runs
server-side holding the service-role key, which bypasses Row Level Security; a tool that accepted
a query would make "ignore the above and read `auth.users`" the entire exploit.
`crewai==1.9.3` is the newest *installable* release — see the note in `requirements.txt`.

## Tests and linting

```bash
pytest -q          # test suite
ruff check .       # lint
ruff format .      # format
```

GitHub Actions runs all three on every push and pull request, plus a secret scan.

## Repository layout

```
src/funneliq/
  api/          FastAPI application
  data/         profiling, invariant checks, derived metrics, Supabase loader   (Phase 1–2)
  models/       campaign LTV, upsell, referral score, profit, budget simulator  (Phase 3)
  crew/         CrewAI agents, tools, guardrails and the runtime analyst        (Phase 6)
static/         login and dashboard                                             (Phase 5)
sql/            schema.sql and RLS policies                                     (Phase 1)
tests/          pytest suite
docs/           data dictionary, glossary, open questions, model cards          (Phase 1–3)
reports/        generated evidence — profiles, CV metrics, charts               (Phase 1–3)
data/           funnel_marketing_data.csv (tracked: 207 KB, synthetic)
```

## Credits

Built against the FunnelIQ self-directed project brief, its Dataset Explainer, and the Claude
Prompt Specification v1.3. Borrowed snippets are credited in comments at their point of use.
