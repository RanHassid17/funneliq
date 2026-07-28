# Shared project state

The compact handoff record required by the Prompt Specification §16.6. A fresh session should be
able to read this file plus `PLAN.md` and resume without redoing discovery.

**Never put secrets in this file.** Keys live in `.env` (gitignored) and in Railway variables.

Last updated: 2026-07-28 · after Phase 1 code merge

---

## Current milestone

**Phase 1 code complete and merged** (PR #2). **Not yet applied to Supabase.**

Remaining before Phase 2: apply `sql/schema.sql` then `sql/rls_policies.sql` to the Supabase
project, run the loader, and verify RLS refuses an unauthenticated read.

**Blocker:** the local `supabase` CLI is a shim whose `supabase-go` backend is not installed, so
`supabase db query` fails. `supabase projects list` and `supabase link` work (they are implemented
in the shim). Either install the full CLI —

```bash
brew install supabase/tap/supabase
```

— or paste the two SQL files into the Supabase dashboard SQL editor. Both files are idempotent.

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

Supabase uses the **newer key scheme** (`sb_publishable_…` / `sb_secret_…`) rather than legacy
`anon` / `service_role` JWTs. The publishable key maps to `SUPABASE_ANON_KEY`, the secret key to
`SUPABASE_SERVICE_ROLE_KEY`.

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
8. Each phase is one feature branch → PR → merge.

## Verified evidence

Measured against all 3,500 rows during planning (`PLAN.md` §2). To be re-derived as committed
code in Phase 1 — nothing is quoted in `README.md` or `REPORT.md` until it exists in `reports/`.

- Invariants holding 3,500/3,500: `answered + not_answered == num_leads`; follow-up counts
  non-increasing; `followup_1 ≤ leads_answered`; `closed + not_closed == followup_5`;
  `CAC == floor(ad_budget / closed)`.
- `purchased == 1` ⟺ `cumulative_profit > 0`, zero off-diagonal.
- Mid budget tier (₪2,000–5,000) dominates: 66.3% upsell, 64.2% referral, 33.6-month LTV,
  6.79 ROAS — versus 0.52 ROAS for the High tier.
- Follow-up dropout by stage: 21.7 → 25.7 → 18.6 → 10.4 → 29.2%. **The sales manager's "waste of
  time after the 3rd follow-up" claim is contradicted** — stage 4 is the most retentive.
- ₪50,000 as a single campaign is **2.5× the observed maximum** (₪20,000) — out of distribution.

## Completed validations

| What | Evidence |
|---|---|
| CI green | run 30337911832 — `secret-scan` ✓, `test` ✓ |
| Local toolchain | ruff clean, ruff format clean, 2 tests pass |
| Live health | `HTTP 200`, `commit: 40924787…` matching `master` HEAD |
| Push triggers redeploy | `4092478` deployed with `reason: deploy`; dashboard shows auto-deploy enabled on `master` |
| Survives restart | forced redeploy reset uptime 206.3s → 19.7s, recovered unattended |
| Feature branch + PR | PR #1 merged |

## Artifacts

`PLAN.md` · `README.md` · `pyproject.toml` · `requirements.txt` / `requirements-dev.txt` ·
`Procfile` · `railway.json` · `.env.example` · `.github/workflows/ci.yml` ·
`src/funneliq/api/main.py` · `tests/test_health.py`

## Open blockers

1. **`supabase db query` is unusable** — the local CLI is a shim missing its `supabase-go`
   backend. Schema and RLS must be applied via the dashboard SQL editor or a full CLI install.
2. Supabase env vars are not yet set on the Railway service (needed from Phase 4).

`.env` exists locally with all four Supabase values populated (verified non-empty, not read).

## Human approval gates still ahead

Applying RLS policies (Phase 1), any destructive migration, credential rotation, exposing a new
public endpoint, major architecture change.

## Next action

**Finish Phase 1 against the live database:**

1. Apply `sql/schema.sql`, then `sql/rls_policies.sql` (SQL editor, or the full CLI).
2. `PYTHONPATH=src python -m funneliq.data.load_to_supabase` — expect 3,490 rows upserted.
3. Verify the row count in Postgres, that a second run changes nothing, and that an
   **unauthenticated** select is refused by RLS. Capture the actual error as evidence.

Then **Phase 2** — `metrics.py`, `features.py` (the per-checkpoint allowlists), and Work Package 1.
Owner: Data & ML Engineer.
