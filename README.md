# FunnelIQ

Campaign-intelligence application for **Northbound Media**, a performance-marketing agency.
FunnelIQ turns two years of funnel data into decision-ready answers: which campaigns produce
long-lived customers, where leads fall out of the follow-up sequence, and how to allocate a
₪50,000 monthly ad budget.

**Live URL:** <https://funneliq-api-production.up.railway.app>
· health check: [`/health`](https://funneliq-api-production.up.railway.app/health)

> **Build status: Phase 0 of 8 complete.** The skeleton is deployed on Railway with CI green.
> Data, models, auth and the dashboard land in later phases. [`PLAN.md`](PLAN.md) is the full
> roadmap and the record of every decision behind it.
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
Browser (login.html, dashboard.html)
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

Every protected route returns **401** without a valid Supabase JWT. Interactive docs at `/docs`.

**`/health` and `/ready` are deliberately different.** Liveness must not depend on the database —
a health check that fails during a brief Supabase blip makes the platform restart a process that
was never broken. Readiness *does* check it, and reports each dependency separately, because "the
database is unreachable" and "the models were never trained" need different fixes.

**The LTV and profit endpoints serve the budget baseline, not the ensembles** — the honest
consequence of boosting failing to beat it. Each response names the model that answered it.

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
  crew/         CrewAI agents and the runtime analyst                           (Phase 6)
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
