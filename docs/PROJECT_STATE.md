# Shared project state

The compact handoff record required by the Prompt Specification §16.6. A fresh session should be
able to read this file plus `PLAN.md` and resume without redoing discovery.

**Never put secrets in this file.** Keys live in `.env` (gitignored) and in Railway variables.

Last updated: 2026-07-28 · after Phase 3

---

## Current milestone

**Phases 0–3 complete** (PRs #1–#4 merged). Next: **Phase 4 — API + auth**.

All six analytical work packages are answered in `REPORT.md`. Four models are trained, evaluated
against naive baselines, and committed with provenance cards.

### The Phase 3 result that shapes everything after it

**Two of the four models do not beat their naive baseline**, and this is reported rather than
hidden:

| Model | Checkpoint | Result | vs baseline |
|---|---|---|---|
| `ltv_months` | C2 | R² 0.8532 | **−0.0028 — loses** to budget-only group mean (0.8560) |
| `cumulative_profit` | C0 | R² 0.6488 | **+0.00005 — exact tie** |
| `upsell` | C2 | F1 0.7039, recall 0.7640 | **+0.704 F1** over majority class |
| `referral_score` | C1 | F1 0.7176, recall 0.8139 | **+0.718 F1** |

`ad_budget` has only 16 distinct values and drives the regression targets almost entirely, so a
group mean over those categories is already near-optimal. **Phase 4 should serve the baseline for
LTV and profit**, keeping the ensembles only for comparison. See `docs/MODEL_CARDS.md`.

**Leakage smoke test:** LTV R² 0.853 → **0.946** when the forbidden post-campaign columns are
added. That is the measured cost of a leak.

**Budget simulator:** recommends **25 × ₪2,000** (ROAS 10.87); refuses to rank 1 × ₪50,000, which
is 2.5× the largest observed budget.

## Live infrastructure

| Resource | Value |
|---|---|
| GitHub | <https://github.com/RanHassid17/funneliq> (public), default branch `master` |
| Railway project | `funneliq` · `e2139d0c-ca9f-4cf6-b8e5-92c62443ef11` |
| Railway service | `funneliq-api` · `a7b12d7b-ce3a-4bf7-83f9-53dd6fa7d15c` |
| Railway environment | `production` · `2a38351f-80de-4141-a518-ad5196356847` |
| Live URL | <https://funneliq-api-production.up.railway.app> |
| Supabase project | ref `xlrhobtbzvvdbexlupxj`, org `ecplwmwwbmkzqxexzkts` |
| Supabase URL | `https://xlrhobtbzvvdbexlupxj.supabase.co` |
| Supabase Postgres | 17.6.1, region `ap-northeast-1` (Tokyo), `ACTIVE_HEALTHY` |
| Table | `public.campaigns`, **3,490 rows**, RLS enabled |

`.env` holds all four Supabase values, using the **legacy JWT key scheme** (`eyJ…` anon and
service-role keys), not the newer `sb_publishable_` / `sb_secret_` style.

**Tooling note:** the local `supabase` CLI is a shim missing its `supabase-go` backend, so
`supabase db query` does not work. `projects list` and `link` do. Schema changes go through the
dashboard SQL editor.

**Latency note:** Supabase is in Tokyo, Railway is US — expect ~150–200 ms per runtime query.

## Accepted decisions

1. **One row = one campaign.** Never a customer. Enforced in language, schema, charts and API.
2. Stack: FastAPI + static HTML/JS, Supabase Postgres + Auth, Railway, CrewAI for the analyst.
3. Feature allowlists are **per prediction checkpoint** (C0 pre-launch, C1 after lead response,
   C2 after follow-up 2, C3 post-campaign). See `PLAN.md` §7.
4. `customer_acquisition_cost` is **excluded from every pre-outcome model** — it is
   `floor(ad_budget / closed)` in 3,500/3,500 rows, so it encodes the sales result.
5. The `purchased` model is **dropped** — `purchased == 1` ⟺ `cumulative_profit > 0` exactly.
6. Naive baselines are mandatory: budget-only reaches **R² 0.664** on profit, **R² 0.856** on LTV.
7. `/health` is public and does not touch Supabase; readiness gets a separate endpoint in Phase 4.
8. Rows failing a structural check are **flagged, not dropped**. Only the 10 exact duplicates go.
9. Missing `ltv_months` / `cumulative_profit` stay **NULL, never zero-filled**.
10. Each phase is one feature branch → PR → merge.

## Verified evidence

Reproduced by committed code into `reports/profile.json` and `reports/invariants.json`.

- Invariants holding 3,500/3,500: `answered + not_answered == num_leads`; follow-ups
  non-increasing; `followup_1 ≤ leads_answered`; `closed + not_closed == followup_5`;
  `CAC == floor(ad_budget / closed)`; `purchased ⟺ profit > 0`; no negative values.
- 155 campaigns closed 1–8 deals yet collected nothing (`purchased = 0`, profit 0, upsell 0).
- Mid budget tier (₪2,000–5,000) dominates: 66.3% upsell, 64.2% referral, 33.6-month LTV,
  6.79 ROAS — versus 0.52 ROAS for the High tier.
- Follow-up dropout by stage: 21.7 → 25.7 → 18.6 → 10.4 → 29.2%. **The sales manager's "waste of
  time after the 3rd follow-up" claim is contradicted** — stage 4 is the most retentive.
- Leads per ₪1,000 fall from 25.8 at ₪500 to 6.07 at ₪20,000 — steep diminishing returns.
- ₪50,000 as a single campaign is **2.5× the observed maximum** (₪20,000) — out of distribution.

## Completed validations

| What | Evidence |
|---|---|
| CI green | `secret-scan` ✓, `test` ✓ on every push |
| Local toolchain | ruff clean, ruff format clean, **83 tests pass** |
| Live health | `HTTP 200`, `commit: 40924787…` matching `master` HEAD |
| Push triggers redeploy | `4092478` deployed with `reason: deploy` |
| Survives restart | forced redeploy reset uptime 206.3s → 19.7s, recovered unattended |
| Schema + RLS applied | applied via the Supabase SQL editor |
| Rows loaded | **3,490** = 3,500 source − 10 exact duplicates |
| **Loader is idempotent** | second full run → still exactly 3,490 rows |
| **RLS blocks anonymous read** | `HTTP 401`, `42501 permission denied for table campaigns` |
| **RLS blocks anonymous insert** | `HTTP 401`, same refusal |
| Quality flags persisted | 4 rows `ltv_months_missing`, 29 `cumulative_profit_missing` |
| Feature branches + PRs | PR #1–#4 merged |
| Models trained with provenance | 4 cards in `models/*.json`; a test asserts each still matches the current feature policy |
| Leakage cost measured | LTV R² 0.853 → 0.946 with forbidden columns |
| Leakage policy enforced | `test_features.py` asserts CAC and `purchased` cannot reach any pre-outcome model |
| No infinities in derived metrics | `test_metrics.py` checks all 24 derived columns on all 3,500 rows |

## Artifacts

`PLAN.md` · `README.md` · `pyproject.toml` · `requirements.txt` / `requirements-dev.txt` ·
`Procfile` · `railway.json` · `.env.example` · `.github/workflows/ci.yml` ·
`sql/schema.sql` · `sql/rls_policies.sql` ·
`src/funneliq/api/main.py` · `src/funneliq/data/{__init__,invariants,profile,load_to_supabase}.py` ·
`src/funneliq/data/{metrics,features}.py` · `tests/{test_health,test_invariants,test_metrics,test_features,helpers}.py` ·
`docs/{DATA_DICTIONARY,GLOSSARY,OPEN_QUESTIONS,PROJECT_STATE}.md` ·
`src/funneliq/models/{__init__,evaluate,registry,estimators,train,budget}.py` · `tests/test_models.py` ·
`models/*.{pkl,json}` · `reports/{profile,invariants,models,budget_simulation}.json` ·
`docs/MODEL_CARDS.md` · `data/funnel_marketing_data.csv` · `REPORT.md`

## Open blockers

1. Supabase env vars are not yet set on the Railway service (needed from Phase 4).
2. `ANTHROPIC_API_KEY` is unset — only affects the Phase 6 CrewAI analyst, which degrades to a
   503 with a clear message rather than crashing.

## Human approval gates still ahead

Destructive migrations, credential rotation, exposing a new public endpoint, major architecture
change. (RLS was applied by the user directly, which cleared that gate.)

## Watch out for

**macOS needs `brew install libomp`** before XGBoost or LightGBM will import; without it they
fail with an opaque `Library not loaded: @rpath/libomp.dylib`.

**CatBoost writes a `catboost_info/` log directory** on every fit. It is gitignored.

macOS/iCloud produced a set of `"<name> 2.py"` duplicate files that were committed once and broke
the test run — pytest collected stale copies alongside the real modules. They are now removed and
`.gitignore`d. If tests suddenly fail on names that look already-fixed, check for them again.

## Next action

**Phase 4 — API + auth**, on branch `feat/api` then `feat/auth`. Per `PLAN.md` §9:

1. Prediction endpoints: `POST /api/predict/{ltv,upsell,referral-score}`,
   `POST /api/budget/simulate`, `GET /api/funnel/dropout`.
2. `GET /api/campaigns` and `GET /api/campaigns/compare?a=&b=` reading **live from Supabase** —
   this satisfies the brief's runtime-read requirement.
3. `auth.py` verifying the Supabase JWT on every protected route. `/health` stays public;
   everything else returns 401 without a valid token.
4. A readiness endpoint that *does* check Supabase, kept separate from `/health`.

**Serve the baseline, not the ensemble, for `ltv_months` and `cumulative_profit`** — see the
milestone section above.

**Prerequisite:** set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` and
`SUPABASE_JWT_SECRET` as Railway service variables. They exist locally in `.env` but not yet on
the deployed service.

🔒 Security review before merge. Owner: Backend Engineer.
