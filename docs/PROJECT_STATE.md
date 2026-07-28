# Shared project state

The compact handoff record required by the Prompt Specification §16.6. A fresh session should be
able to read this file plus `PLAN.md` and resume without redoing discovery.

**Never put secrets in this file.** Keys live in `.env` (gitignored) and in Railway variables.

Last updated: 2026-07-28 · after Phase 1

---

## Current milestone

**Phases 0 and 1 complete and verified against live infrastructure.** In progress: Phase 2
(derived metrics, per-checkpoint feature policy, Work Package 1).

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
| Local toolchain | ruff clean, ruff format clean, **26 tests pass** |
| Live health | `HTTP 200`, `commit: 40924787…` matching `master` HEAD |
| Push triggers redeploy | `4092478` deployed with `reason: deploy` |
| Survives restart | forced redeploy reset uptime 206.3s → 19.7s, recovered unattended |
| Schema + RLS applied | applied via the Supabase SQL editor |
| Rows loaded | **3,490** = 3,500 source − 10 exact duplicates |
| **Loader is idempotent** | second full run → still exactly 3,490 rows |
| **RLS blocks anonymous read** | `HTTP 401`, `42501 permission denied for table campaigns` |
| **RLS blocks anonymous insert** | `HTTP 401`, same refusal |
| Quality flags persisted | 4 rows `ltv_months_missing`, 29 `cumulative_profit_missing` |
| Feature branches + PRs | PR #1, PR #2 merged |

## Artifacts

`PLAN.md` · `README.md` · `pyproject.toml` · `requirements.txt` / `requirements-dev.txt` ·
`Procfile` · `railway.json` · `.env.example` · `.github/workflows/ci.yml` ·
`sql/schema.sql` · `sql/rls_policies.sql` ·
`src/funneliq/api/main.py` · `src/funneliq/data/{__init__,invariants,profile,load_to_supabase}.py` ·
`tests/{test_health,test_invariants}.py` ·
`docs/{DATA_DICTIONARY,GLOSSARY,OPEN_QUESTIONS,PROJECT_STATE}.md` ·
`reports/{profile,invariants}.json` · `data/funnel_marketing_data.csv`

## Open blockers

1. Supabase env vars are not yet set on the Railway service (needed from Phase 4).
2. `ANTHROPIC_API_KEY` is unset — only affects the Phase 6 CrewAI analyst, which degrades to a
   503 with a clear message rather than crashing.

## Human approval gates still ahead

Destructive migrations, credential rotation, exposing a new public endpoint, major architecture
change. (RLS was applied by the user directly, which cleared that gate.)

## Watch out for

macOS/iCloud produced a set of `"<name> 2.py"` duplicate files that were committed once and broke
the test run — pytest collected stale copies alongside the real modules. They are now removed and
`.gitignore`d. If tests suddenly fail on names that look already-fixed, check for them again.

## Next action

**Phase 2** on branch `feat/eda`:

1. `src/funneliq/data/metrics.py` — derived campaign metrics per `PLAN.md` §6.3, every ratio
   declaring its denominator and returning `None` on a zero denominator.
2. `src/funneliq/data/features.py` — the per-checkpoint allowlists from `PLAN.md` §7, with a test
   asserting no excluded column can reach any feature matrix.
3. Work Package 1 write-up from `reports/profile.json`.

Owner: Data & ML Engineer.
