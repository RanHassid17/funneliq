# Shared project state

The compact handoff record required by the Prompt Specification §16.6. A fresh session should be
able to read this file plus `PLAN.md` and resume without redoing discovery.

**Never put secrets in this file.** Keys live in `.env` (gitignored) and in Railway variables.

Last updated: 2026-07-29 · after Phase 6

---

## Current milestone

**Phases 0–6 complete** (PRs #1–#9 merged; Phase 6 on `feat/crew`).
Next: **Phase 7 — QA & traceability**.

**Phase 6 caveat: the analyst is built and its degradation path is verified, but no answer has
been produced by a real model.** `ANTHROPIC_API_KEY` is unset locally and on Railway, and setting
it creates ongoing cost — a human approval gate. Until someone sets it, `/api/ask` returns 503,
the dashboard hides the panel, and everything else works. Do not describe the analyst as
"working" anywhere; describe it as built and unexercised.

**The brief's definition of done is met.** A stranger can open the live URL, sign in,
get campaign predictions, and read the funnel and budget insights unaided. Confirmed
working in a real browser by the user on 2026-07-28.

The API is live and login-gated: `/api/*` returns 401 without a valid Supabase JWT, `/api/campaigns` reads Postgres per request, and predictions are served from the committed model artifacts. Interactive docs at `/docs`.

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

**This was challenged and held.** PR #5 swept **114 tuned configurations** across all three
libraries (`reports/tuning_ltv.json`); **zero** beat the baseline. Best was XGBoost at R² 0.854965
versus 0.855967. Every top config was shallow with a low learning rate — the tuner's best move is
to make the model simpler, converging toward the group mean without reaching it. A test asserts
this, so if it ever stops holding, CI fails and the write-up gets corrected.

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

**Auth scheme:** this project signs user sessions with **asymmetric ES256 keys** served at
`/auth/v1/.well-known/jwks.json`. `auth.py` verifies against JWKS and falls back to HS256
only for projects still signing symmetrically. `SUPABASE_JWT_SECRET` is optional and unused
here. Note the trap: the **anon key is** a legacy HS256 JWT, but it is a long-lived API key,
not a session token -- assuming both used the same scheme broke every sign-in until PR #9.

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
| Local toolchain | ruff clean, ruff format clean, **141 tests pass** |
| Live health | `HTTP 200`, `commit: 40924787…` matching `master` HEAD |
| Push triggers redeploy | `4092478` deployed with `reason: deploy` |
| Survives restart | forced redeploy reset uptime 206.3s → 19.7s, recovered unattended |
| Schema + RLS applied | applied via the Supabase SQL editor |
| Rows loaded | **3,490** = 3,500 source − 10 exact duplicates |
| **Loader is idempotent** | second full run → still exactly 3,490 rows |
| **RLS blocks anonymous read** | `HTTP 401`, `42501 permission denied for table campaigns` |
| **RLS blocks anonymous insert** | `HTTP 401`, same refusal |
| Quality flags persisted | 4 rows `ltv_months_missing`, 29 `cumulative_profit_missing` |
| Feature branches + PRs | PR #1–#9 merged |
| **End-to-end sign-in works** | user confirmed the deployed dashboard renders every panel after login |
| **Dashboard live** | `/` login screen, `/dashboard.html` panels, both serving on Railway |
| **Anon key only in browser** | `/api/config` serves URL + anon key; a test asserts the service-role key can never appear there |
| **Auth gate verified** | 10 protected routes return 401 for no/forged/expired/wrong-audience/malformed/subject-less tokens |
| **Live runtime Supabase read** | `/ready` on the deployed service reports 3,490 campaigns reachable |
| Deployed predictions work | live `/api/predict/referral-score` returns 75.0, matching local |
| Models trained with provenance | 4 cards in `models/*.json`; a test asserts each still matches the current feature policy |
| Leakage cost measured | LTV R² 0.853 → 0.946 with forbidden columns |
| Leakage policy enforced | `test_features.py` asserts CAC and `purchased` cannot reach any pre-outcome model |
| No infinities in derived metrics | `test_metrics.py` checks all 24 derived columns on all 3,500 rows |
| **CrewAI works on Python 3.13** | `crewai==1.9.3` installs and imports on 3.13.0; the §13 risk is retired |
| **Analyst degrades, not crashes** | without a key: `/api/ask` → 503, `/health` `/api/models` `/api/predict/*` → 200 |
| **Crew constructs against the real API** | 8 build roles + Analyst + Reviewer + 4 tools + Crew all instantiate |
| **Analyst is not part of readiness** | `/ready` verdict is identical with and without the key |
| **Agent tools take no SQL** | `query_campaigns` signature is `{campaign_id, limit}`; row cap enforced at 50 |
| NOT verified: a real analyst answer | needs `ANTHROPIC_API_KEY`; no LLM call has been made |

## Artifacts

`PLAN.md` · `README.md` · `pyproject.toml` · `requirements.txt` / `requirements-dev.txt` ·
`Procfile` · `railway.json` · `.env.example` · `.github/workflows/ci.yml` ·
`sql/schema.sql` · `sql/rls_policies.sql` ·
`src/funneliq/api/main.py` · `src/funneliq/data/{__init__,invariants,profile,load_to_supabase}.py` ·
`src/funneliq/data/{metrics,features}.py` · `tests/{test_health,test_invariants,test_metrics,test_features,helpers}.py` ·
`docs/{DATA_DICTIONARY,GLOSSARY,OPEN_QUESTIONS,PROJECT_STATE}.md` ·
`src/funneliq/models/{__init__,evaluate,registry,estimators,train,budget,tuning}.py` · `tests/test_models.py` ·
`models/*.{pkl,json}` · `reports/{profile,invariants,models,budget_simulation,tuning_ltv}.json` ·
`docs/MODEL_CARDS.md` · `data/funnel_marketing_data.csv` · `REPORT.md` ·
`src/funneliq/crew/{__init__,guardrails,tools,agents,analyst,run}.py` ·
`src/funneliq/api/routes/ask.py` · `tests/test_crew.py` · `static/{dashboard.html,app.js,styles.css}`

## Open blockers

2. `ANTHROPIC_API_KEY` is unset — only affects the Phase 6 CrewAI analyst, which degrades to a
   503 with a clear message rather than crashing.

## Human approval gates still ahead

Destructive migrations, credential rotation, exposing a new public endpoint, major architecture
change. (RLS was applied by the user directly, which cleared that gate.)

## Watch out for

**Tests that mint their own tokens prove nothing about the identity provider.** Seven auth
tests passed while every real sign-in failed, because the tests and the implementation shared
the same wrong assumption about the signing algorithm. `tests/test_auth_asymmetric.py` now
signs with a real EC key and verifies through a stubbed JWKS endpoint.

**`/health` cannot catch a broken app.** It deliberately touches nothing external, so the
Phase 4 deploy passed its healthcheck while crashing on every real request. **Post-deploy
verification must hit `/ready`**, which checks Supabase and the model artifacts.

**Never import `models.train` from the API.** It pulls in LightGBM and XGBoost, whose native
libraries need OpenMP at import time. Use `data.frames.load_campaign_frame`. CatBoost still
needs OpenMP to unpickle, which is why the Railway service sets
`RAILPACK_DEPLOY_APT_PACKAGES=libgomp1`.

**macOS needs `brew install libomp`** before XGBoost or LightGBM will import; without it they
fail with an opaque `Library not loaded: @rpath/libomp.dylib`.

**CatBoost writes a `catboost_info/` log directory** on every fit. It is gitignored.

**`crewai` is pinned to 1.9.3 because 1.10–1.15 are uninstallable, not because of Python.**
They require `lancedb>=0.29.2`; the newest lancedb on PyPI is 0.25.3, so the resolver fails on
3.12 and 3.13 alike. Do not "fix" this by changing the Python version.

**Nothing in `funneliq/crew/` may import `crewai` at module scope.** The API imports the package
on startup; a top-level import would put chromadb/onnxruntime/grpc in the service's critical path
and turn one broken native library into a dead deployment.

macOS/iCloud produced a set of `"<name> 2.py"` duplicate files that were committed once and broke
the test run — pytest collected stale copies alongside the real modules. They are now removed and
`.gitignore`d. If tests suddenly fail on names that look already-fixed, check for them again.

## Login

No user account exists yet in Supabase Auth. The login screen's **Create account** button
self-serves it. Depending on project settings Supabase may require email confirmation.

## Next action

**Phase 7 — QA & traceability.** Walk the `PLAN.md` §12 requirements matrix, reconcile every
dashboard number against SQL, and run adversarial checks against the deployed service.

Two things left over from Phase 6, both waiting on a human decision rather than on code:

1. **Set `ANTHROPIC_API_KEY` on Railway** (approval gate: ongoing cost). Until then the deployed
   analyst answers 503. After setting it, verify with `GET /api/ask/status` → `available: true`
   and one real question through the dashboard.
2. **Watch the Railway build.** Phase 6 adds ~220 MB to the image (chromadb, onnxruntime, grpc,
   kubernetes). Verify `/ready` after the deploy, not `/health` — `/health` touches nothing and
   would pass over a broken import.

Then **Phase 7 (QA + traceability)** and **Phase 8 (docs)**.

Owner: Data & ML Engineer.
