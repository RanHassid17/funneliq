# FunnelIQ — Implementation Plan

Marketing-intelligence tool for Northbound Media: an authenticated, deployed application
that predicts customer lifetime, upsell probability and super-customer likelihood, analyses
follow-up drop-off, and optimises a ₪50,000 monthly ad budget.

Status: **discovery complete, nothing built yet.**

---

## 1. Verified dataset facts

Profiled from `funnel_marketing_data.csv` (3,500 rows × 19 columns). These are measured,
not assumed:

| Fact | Value |
|---|---|
| Shape | 3,500 × 19 |
| Missing values | `ltv_months` 4, `cumulative_profit` 29 → 33 incomplete rows |
| Exact duplicate rows | 10 |
| `referred` | Yes 1,354 / No 2,146 (38.7% positive) |
| `upsell` | 1 → 1,466 / 0 → 2,034 (41.9% positive) |
| `purchased` | 1 → 3,163 / 0 → 337 |
| `ad_budget` | ₪500 – ₪20,000, median ₪3,000 |
| `ltv_months` | 1 – 56, mean 22.0 |
| `cumulative_profit` | 0 – 149,959, median 9,035 |
| `customer_acquisition_cost` | 0 – 6,666, median 1,000 |

**Note on class imbalance.** Both classification targets sit near 40/60, which is *mild*.
The brief requires imbalance handling (`scale_pos_weight` / class weights) and we will
implement it, but we report honestly that it is not the dominant lever here rather than
overclaiming its effect.

## 2. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Stack | FastAPI + static HTML/JS | Brief's suggested stack; gives a clean anon-key/service-key split; trivial Railway deploy |
| Repo | public `RanHassid17/funneliq` | Own commit history as a portfolio artifact |
| Agents | real CrewAI package, shipped in the repo | Part of the solution, not just the build process |
| Deploy | Railway, auto-deploy from GitHub | Required by brief |
| Auth | Supabase Auth, email + password | Required by brief |

## 3. Assumptions (open to correction)

1. **Row granularity.** The brief calls each row a "customer/campaign record", but the
   columns mix campaign-level fields (`num_leads`, `closed` — mean 3.0 deals per row) with
   customer-level outcomes (`ltv_months`, `upsell`, `referred`). We treat a row as **a
   campaign carrying a representative customer outcome**, document it in the README, and
   frame Package 6's simulator accordingly. We do not pretend the grain is clean.
2. **CrewAI needs an LLM at runtime**, meaning an `ANTHROPIC_API_KEY` on Railway and a
   per-call cost. The design below bounds that and degrades gracefully when the key is absent.
3. Free tiers only (Supabase + Railway). No paid infrastructure.
4. The source CSV (207 KB, synthetic) is tracked in `data/`. It is not a "data dump" in the
   sense the brief warns about, and tracking it keeps the repo reproducible.

## 4. Architecture

```
Browser (login.html, dashboard.html)
  └─ supabase-js ── ANON KEY ONLY ──────────► Supabase Auth
  └─ fetch(Bearer JWT) ─────────────────────► FastAPI on Railway
                                                ├─ verifies Supabase JWT server-side
                                                ├─ models/*.pkl → predictions
                                                ├─ Supabase client (SERVICE KEY,
                                                │    server-side only) ──► Postgres + RLS
                                                └─ crew/ → CrewAI runtime analyst
```

The anon-key-in-browser / service-key-on-server split is the security property the brief
actually grades. It falls out naturally from this shape rather than being bolted on.

## 5. Repository layout

```
funneliq/
  src/funneliq/
    data/      profile.py  load_to_supabase.py  features.py   # feature policy lives here
    models/    ltv.py  upsell.py  supercustomer.py  budget.py
    api/       main.py  auth.py  db.py  routes/
    crew/      agents.py  tasks.py  tools.py  crews.py
  static/      login.html  dashboard.html  app.js  styles.css
  sql/         schema.sql  rls_policies.sql
  tests/
  data/        funnel_marketing_data.csv
  reports/     *.json  *.png          # generated evidence, committed
  .github/workflows/ci.yml
  README.md  REPORT.md  PLAN.md  requirements.txt  .env.example  .gitignore
```

## 6. Feature policy — the leakage core

Decided per target, by asking *what would Northbound actually know at the moment this
prediction is made?*

| Target | Prediction moment | Excluded as leakage | Why |
|---|---|---|---|
| `ltv_months` | customer onboarded | `cumulative_profit`, `upsell`, `referred` | Profit accrues *over* the lifetime — it is a near-deterministic function of the target. Upsell and referral happen later. |
| `upsell` | at / just after initial purchase | `cumulative_profit`, `referred`, **`ltv_months`** | Total lifetime is not known at the moment we decide who to approach. |
| `referred` (0–100 score) | early funnel only (per brief) | `ltv_months`, `upsell`, `cumulative_profit` | The brief explicitly asks for a score from *early funnel data*. |
| `cumulative_profit` | pre-campaign | `ltv_months`, `upsell`, `referred` | The simulator must run before any spend, so only budget and funnel structure are inputs. |

**The sharp point worth writing up.** The brief's suggested business rule —
*"if LTV > X and CAC < Y, flag for outreach"* — uses `ltv_months`, which we exclude from
the upsell model as leakage. The rule therefore holds an information advantage the model
does not. Comparing them fairly means saying so explicitly. This is the "defend your
choice" reasoning the brief is looking for.

Enforcement: `features.py` holds an explicit allowlist per target, and a test asserts no
excluded column ever reaches a model's feature matrix.

## 7. Phases

Each phase is one feature branch → PR → merge. This satisfies the git-workflow requirement
organically rather than staging a token PR at the end.

### Phase 0 — skeleton deployed (first)
Branch: `feat/skeleton`
Repo init, `.gitignore`, pinned `requirements.txt`, FastAPI returning `/health`, Railway
linked to GitHub, CI running lint plus one trivial test.
Deploy *before* there is any real code — the brief's own advice, and correct: auth and
deployment bugs are far easier to debug against an empty app.

**Validation:** `curl https://<railway-url>/health` returns 200; a push triggers redeploy;
CI is green.

### Phase 1 — data layer
Branch: `feat/data`
`sql/schema.sql` (typed columns, `id` primary key, `referred` stored as boolean rather than
text), `load_to_supabase.py` as a repeatable idempotent loader, RLS enabled with an
authenticated-read policy, and a deterministic `profile.py` writing `reports/profile.json`.

Decisions taken here: drop the 10 exact duplicates; drop rows with a missing target for the
model that targets it (rather than imputing a target); document both.

**Validation:** row count in Postgres equals the loaded count; an unauthenticated `select`
is refused by RLS.

### Phase 2 — feature policy + EDA
Branch: `feat/eda`
Implements §6 as code, plus Work Package 1: missing-value write-up, correlation against
`cumulative_profit`, the shape of `ad_budget` → `num_leads` (diminishing returns?), and
conversion rate (`closed / num_leads`) across budget tiers — Low ≤1500, Mid 2000–5000,
High >5000.

**Validation:** `pytest` asserts the feature allowlists hold.

### Phase 3 — models
Branch: `feat/models`

- **Package 2** `ltv_months`: XGBoost, LightGBM, CatBoost; 5-fold CV; RMSE and R²;
  feature importances compared across all three.
- **Package 3** `upsell`: the same three as classifiers with imbalance handling and
  stratified 5-fold CV; Accuracy, Precision, Recall, F1; importances for the best model;
  plus the business-rule comparison from §6.
- **Package 4** `referred`: CatBoost with hyperparameter search over learning rate, depth
  and iterations; calibrated into a 0–100 super-customer score.
- **Package 5**: dropout rates `followup_1` → `followup_5`, and follow-up counts for deals
  that eventually closed.
- **Package 6**: profit model driven by `ad_budget`, simulating ₪50,000 as 1×₪50k vs
  10×₪5k vs 33×₪1.5k.

Every metric is written to `reports/*.json` with a fixed seed and the git SHA. Nothing is
quoted in `REPORT.md` that does not exist in a reports file.

**Validation:** CV metrics reproduce across two runs. A deliberate leakage smoke test —
training the LTV model *with* `cumulative_profit` and showing the R² jump — is documented
as the demonstration of why it is excluded.

### Phase 4 — API + auth
Branches: `feat/api`, then `feat/auth`
Prediction endpoints per package; one endpoint reading live from Supabase (satisfying the
runtime-read requirement); `auth.py` verifying the Supabase JWT on every protected route.
`/health` stays public, everything else returns 401 without a valid token.

**Validation:** integration tests hitting a protected route with no token, a malformed
token, and a valid token.

### Phase 5 — dashboard
Branch: `feat/dashboard`
Login screen, session handling, working sign-out, then panels: LTV predictor, upsell scorer,
super-customer 0–100 gauge, follow-up dropout chart, budget simulator.

**Validation:** a logged-out visitor sees only the login screen; refresh preserves the
session; sign-out clears it.

### Phase 6 — CrewAI
Branch: `feat/crew`
The eight roles from the prompt specification as real `Agent` definitions, with two entry
points:

- **Offline pipeline** — `python -m funneliq.crew.run --stage analysis`. A sequential
  Planner → ML → QA → Docs crew that reads `reports/*.json` and drafts `REPORT.md`
  sections. No runtime cost; artifacts committed.
- **Runtime feature** — `POST /api/ask`, auth-gated. A two-agent Analyst + Reviewer crew
  with three tools (`query_supabase`, `run_model`, `funnel_stats`) answering natural-language
  business questions from the dashboard. Rate-limited, with a short max-iteration cap, and
  returning 503 with a clear message when `ANTHROPIC_API_KEY` is unset so the app never
  hard-fails on a missing key.

This is what makes CrewAI genuinely part of the product rather than decoration: it is the
founder's "just ask it a question" surface.

**Validation:** the offline crew reproduces a REPORT section from committed reports; the
runtime endpoint answers a known question and refuses cleanly without a key.

### Phase 7 — docs + polish
Branch: `feat/docs`
`README.md` (architecture, local setup, live URL), `REPORT.md` (findings and business
recommendations per package, every figure traceable to `reports/`), `.env.example`, and a
final security pass on key placement.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Model `.pkl` artifacts bloat the repo | Commit them (small for this dataset); revisit if size grows |
| CrewAI compatibility with Python 3.13 | Verify at the start of Phase 6; pin 3.11/3.12 in the Railway runtime if needed |
| Runtime LLM cost | Only `/api/ask` spends; bounded by rate limiting and a max-iteration cap |
| Railway free-tier sleep | Health endpoint plus documented cold-start behaviour in the README |

## 9. Definition of done

A stranger opens the live URL, signs in, gets a prediction for a new customer, sees the
follow-up and budget insights, asks the analyst a question, and reads the recommendations —
without anyone touching anything. The repo explains how it was built and how to run it.

## 10. Next checkpoint

**Phase 0.** Get `/health` live on Railway with CI green. Roughly 45 minutes, and it
de-risks every phase after it.

Open items before Phase 0 completes: confirm whether Supabase and Railway accounts and
projects already exist, or are being provisioned from scratch.
