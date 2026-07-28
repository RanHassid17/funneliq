# FunnelIQ

Campaign-intelligence application for **Northbound Media**, a performance-marketing agency.
FunnelIQ turns two years of funnel data into decision-ready answers: which campaigns produce
long-lived customers, where leads fall out of the follow-up sequence, and how to allocate a
₪50,000 monthly ad budget.

**Live URL:** _not deployed yet — added when Phase 0 completes._

> **Build status: Phase 0 of 8.** The skeleton and its CI pipeline are in place. Data, models,
> auth and the dashboard land in later phases. [`PLAN.md`](PLAN.md) is the full roadmap and the
> record of every decision behind it.

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
