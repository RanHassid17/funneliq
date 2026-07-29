# FunnelIQ — Implementation Plan (v2)

Campaign-intelligence tool for Northbound Media: an authenticated, deployed application that
predicts **campaign** lifetime value, upsell and referral outcomes, analyses funnel drop-off,
compares campaigns, and allocates a ₪50,000 monthly ad budget.

Status: **discovery complete, nothing built yet.**
Revised: 2026-07-28, against `FunnelIQ_Assignment.html`, `FunnelIQ_Dataset_Explainer.html` (v1.0)
and `FunnelIQ_Claude_Prompt_Specification.html` (v1.3).

---

## 0. What changed in v2, and why

The Dataset Explainer and Prompt Spec v1.3 arrived after v1 of this plan. They resolve an
ambiguity v1 hedged on and add requirements v1 did not cover.

| # | Change | Driver |
|---|---|---|
| 1 | **One row = one campaign, definitively.** v1 called it "a campaign carrying a representative customer outcome". That hedge is retired. All schemas, charts, endpoints, labels and recommendations use campaign language. | Explainer §1, §13; Spec §16.9, §17.1 |
| 2 | **Feature allowlists are per prediction *checkpoint*, not per target.** v1 had one allowlist per target. Now: pre-launch / after lead response / after follow-up 2 / post-campaign. | Explainer §8; Spec §17.4 |
| 3 | **Campaign invariant validation** is a first-class deliverable (count consistency, follow-up monotonicity, non-negativity, zero denominators). Absent from v1. | Explainer §5; Spec Appendix A |
| 4 | **Derived campaign metrics** are a named module with defined denominators. Absent from v1. | Explainer §6; Spec §17.3 |
| 5 | **Campaign comparison** added as a required feature (endpoint + dashboard view). Absent from v1. | Spec Appendix A "campaign comparison" |
| 6 | **`customer_acquisition_cost` is confirmed leakage**, not a free feature — it is `floor(ad_budget / closed)` in 3,500/3,500 rows. See §2.2. | Measured, this revision |
| 7 | **Schema gains `campaign_id`, nullable dates, `data_quality_flags`.** | Explainer §11, §12 |
| 8 | Added: data dictionary, business glossary, model cards, open-clarifications register, requirements traceability matrix, human-approval gates, agent output contract, restart-safety check. | Spec §16.5–16.7, §17.5, §17.7; Brief §03 pillars |
| 9 | `purchased` classification **dropped**, with evidence: `purchased == 1` ⟺ `cumulative_profit > 0` exactly, so it is a coarsened copy of the WP6 target rather than a distinct question. See §2.3. | Explainer §7 + measurement |
| 10 | **Mandatory naive baselines** added — a budget-only model already reaches R² 0.66 on profit and 0.86 on LTV, so boosting must beat that to justify itself. See §2.6. | Measured, this revision |
| 11 | The **₪50,000 single-campaign scenario is flagged as out-of-distribution** (2.5× the observed maximum) rather than silently scored. See §2.6. | Measured, this revision |

---

## 1. Canonical interpretation

**Unit of analysis: one advertising campaign / campaign period.** Never one person.

| Field | Campaign meaning |
|---|---|
| `ad_budget` | Total spend assigned to the campaign |
| `num_leads`, `leads_answered`, `leads_not_answered` | Campaign lead counts |
| `followup_1..5` | Leads still engaged after each follow-up round |
| `closed`, `not_closed` | Aggregate campaign sales outcomes |
| `calls_to_closed`, `calls_to_not_closed` | Call effort (mean/total — **unconfirmed**) |
| `customer_acquisition_cost` | Campaign cost per acquired customer |
| `ltv_months` | **Average** lifetime of customers this campaign generated |
| `cumulative_profit` | **Total** profit attributed to the campaign |
| `purchased`, `upsell`, `referred` | Campaign produced ≥1 such outcome (**assumed**) |

**Explicitly out of scope for v1:** individual churn, next-best-action, personalised follow-up,
per-customer referral probability. These need a customer-level table linked by `campaign_id`,
which does not exist. The README and dashboard state this. The 0–100 score is a *campaign
referral-likelihood score*, never "this customer's probability".

### 1.1 Open clarifications register → `docs/OPEN_QUESTIONS.md`

Explainer §4 and Spec §17.7 require these be confirmed with the data owner. There is no data
owner reachable here, so each becomes a **documented, tested assumption** — never a silent one.

| # | Question | Working assumption | How the plan de-risks it |
|---|---|---|---|
| Q1 | Is a row a campaign, a month, an ad set, or a lead cohort? | Campaign/period | Per Explainer §1. No time-series modelling, so month-vs-campaign does not change results |
| Q2 | Is `closed` customers, deals, or calls? | Closed deals ≈ acquired customers | **Resolved.** The CAC identity `CAC = floor(ad_budget / closed)` holds 3,500/3,500 (§2.2, H4) — `closed` is the acquired-customer count |
| Q3 | Are `calls_to_*` totals or averages? | Averages per outcome | Observed range is 0–9 across campaigns of 11–139 leads — implausible as totals, consistent with a per-outcome average. Documented, not assumed silently |
| Q4 | Does `purchased = 1` mean ≥1 purchase? | **Revised: it means the campaign earned revenue** | **Resolved, and it refuted the obvious reading.** `purchased == 1` ⟺ `cumulative_profit > 0` exactly; 155 campaigns closed deals yet recorded `purchased = 0` and zero profit (§2.3) |
| Q5 | Is `ltv_months` observed, estimated, or averaged? | Average across the campaign's customers | Affects wording of every LTV output; never phrased per-customer |
| Q6 | Is `cumulative_profit` gross or net of ad spend? | **Gross** of ad spend | Tested: if net, `cumulative_profit + ad_budget` should reconcile. Decides whether ROAS or net return is the headline metric in WP6 |
| Q7 | Does `upsell = 1` mean ≥1 upsell? | Yes | Documented; no test available |
| Q8 | Does `referred = Yes` mean ≥1 referral? | Yes | Documented; no test available |
| Q9 | Are follow-up stages fixed in time? | Unknown, treated as ordinal stages | No time-based features are built |

Every assumption above is repeated in `README.md`, in the relevant model card, and as a caveat
on the dashboard panel it affects.

---

## 2. Evidence status

Everything below was **measured against all 3,500 rows** during this revision, using pandas
against `funnel_marketing_data.csv`. It is exploratory evidence gathered to make the plan
correct, not a substitute for the deliverable: `profile.py` / `invariants.py` (Phase 1)
regenerate all of it into `reports/*.json` with the seed and git SHA, and **nothing enters
`README.md` or `REPORT.md` until it exists in a committed reports file.**

### 2.1 Profile (verified, n = 3,500 × 19)

Missing: `ltv_months` 4, `cumulative_profit` 29 · exact duplicate rows 10 · no negative values ·
no zero `num_leads`, `leads_answered`, or `followup_5`.
`referred` Yes 1,354 / No 2,146 (38.7%) · `upsell` 1,466 / 2,034 (41.9%) ·
`purchased` 3,163 / 337 (90.4%) ·
`ad_budget` ₪500–20,000, median ₪3,000, **only 16 distinct values** ·
`num_leads` 11–139 (median 40) · `closed` 0–9 (median 3) ·
`ltv_months` 1–56 (median 21, mean 22.0) ·
`cumulative_profit` 0–149,959 (median 9,035) · `customer_acquisition_cost` 0–6,666 (median 1,000).

### 2.2 Structural invariants — confirmed 3,500/3,500

| ID | Rule | Result | Consequence |
|---|---|---|---|
| H1 | `leads_answered + leads_not_answered == num_leads` | ✅ 3500/3500 | Exactly redundant — feed models two of the three, never all three |
| H2 | `followup_1 ≥ … ≥ followup_5`, and `followup_1 ≤ leads_answered` | ✅ 3500/3500 | Retention denominator is `leads_answered`, per Explainer §6 |
| H3 | `closed + not_closed == followup_5` | ✅ 3500/3500 | **Answers Q2.** The funnel-correct close-rate denominator is `followup_5`. WP1 still reports `closed / num_leads` as the brief asks, alongside it |
| H4 | `customer_acquisition_cost == floor(ad_budget / closed)`, `0` when `closed == 0` | ✅ 3500/3500 | **CAC is a deterministic restatement of `closed`.** Given `ad_budget`, handing a model CAC hands it the campaign's sales result. Excluded from every pre-outcome checkpoint — see §7 |

### 2.3 Refuted, and more useful for it

**H5 — `purchased == (closed > 0)` is FALSE** (3,345/3,500). 182 campaigns closed nothing; a
further **155 closed 1–8 deals yet have `purchased = 0`** — and every one of those 155 has
`cumulative_profit = 0` and `upsell = 0`.

The true rule is exact and much sharper:

> **`purchased == 1` ⟺ `cumulative_profit > 0`** — 3,136 / 335, **zero off-diagonal rows.**

So `purchased` is not a funnel outcome; it is a perfect indicator of "did this campaign earn
anything". Two consequences:

1. The optional `purchased` package is **dropped**, but for a stronger reason than v1 gave:
   predicting `purchased` is predicting `profit > 0` — a coarsened copy of the WP6 target, not a
   distinct question.
2. `purchased` is **hard leakage for the profit model**, and `cumulative_profit` is hard leakage
   for any `purchased` model. Both directions are now in the §7 allowlists.

The 155 closed-but-unpaid campaigns are a real segment (deals closed, nothing collected) and get
a `data_quality_flags` entry plus their own line in `REPORT.md`. They are **not** dropped.

### 2.4 Leakage strength — measured, not assumed

Correlation with `cumulative_profit`: `ltv_months` **0.846**, `upsell` 0.652, `purchased` 0.369,
`closed` 0.212, `calls_to_closed` **−0.546**, `customer_acquisition_cost` −0.247,
`ad_budget` **−0.207**.

`ltv_months` at r = 0.85 confirms v1's core call: profit and lifetime are near-substitutes, so
each is excluded from the other's model. The sign on `ad_budget` is negative, which §2.5
explains.

### 2.5 The finding that reshapes WP1, WP5 and WP6

**Mean profit by budget is strongly non-monotonic.** Aggregating the 16 budget levels into the
brief's tiers:

| Tier | n | mean `ltv_months` | upsell rate | referral rate | close rate (`/followup_5`) | mean profit | ROAS |
|---|---|---|---|---|---|---|---|
| Low ≤ 1500 | 780 | 7.9 | 15.6% | 7.7% | 0.33 | ₪2,291 | 2.12 |
| **Mid 2000–5000** | **1,717** | **33.6** | **66.3%** | **64.2%** | **0.43** | **₪21,792** | **6.79** |
| High > 5000 | 1,003 | 13.2 | 20.5% | 19.1% | 0.30 | ₪5,186 | 0.52 |

The mid tier wins on *every* measure, by wide margins — and the High tier is the only one where
ROAS < 1. This directly answers WP1's "which tier converts best, and does that surprise you?" and
largely pre-determines WP6's recommendation: **spread, don't concentrate.**

Two supporting facts:

- **Diminishing returns are real and steep.** Leads per ₪1,000 falls monotonically from 25.8 at
  ₪500 to 6.07 at ₪20,000 — a ~4× loss of efficiency across the range.
- **Follow-up dropout (aggregate, stage-over-stage): 21.7% → 25.7% → 18.6% → 10.4% → 29.2%.**
  Dropout *falls* through stages 3 and 4, then spikes at stage 5. The sales manager's "after the
  3rd follow-up we're wasting time" is **contradicted by the data**: stage 4 is the most
  retentive stage in the funnel. That is WP5's headline, and it is exactly the kind of
  counter-intuitive result the brief is fishing for.
- **`calls_to_closed` is inversely related to campaign value**: campaigns closing in 1–2 calls
  average ₪23k profit and 36-month LTV; those needing 6+ calls average ~₪1.8k and ~6.7 months.

### 2.6 Three consequences the plan must respect

1. **A budget-only model is strong, not weak.** A 5-fold group-mean baseline using `ad_budget`
   *alone* scores **R² 0.66 on `cumulative_profit`** (RMSE 6,489 vs 11,226 for a global mean) and
   **R² 0.86 on `ltv_months`**. v1 assumed the pre-launch model would be near-useless; that was
   wrong. It also raises the bar: **gradient boosting must beat R² 0.66 / 0.86 to have earned its
   place**, and those become the mandatory naive baselines in every model card.

2. **₪50,000 in one campaign is out of distribution.** The observed maximum is ₪20,000, so the
   brief's "1 × ₪50k" scenario sits 2.5× beyond any training data. Tree ensembles cannot
   extrapolate — they will return the ₪20,000 leaf value and present it as a confident
   prediction. The simulator must **flag that scenario as unsupported extrapolation** rather than
   quietly scoring it. Reporting "concentrating loses" while silently extrapolating would be the
   exact failure mode the brief warns about.

3. **This structure is suspiciously clean.** A discrete 16-value budget grid with a sharp
   ₪2,000–5,000 sweet spot suggests the generator encoded a regime rather than the market
   revealing one. The recommendation is correct *for this dataset*; `REPORT.md` will say so and
   propose a real-world validation (a controlled budget split) before ₪50,000 moves on its
   strength. This is labelled a **hypothesis about the world**, not a finding.

---

## 3. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Stack | FastAPI + static HTML/JS | Brief's suggested stack; gives a clean anon-key/service-key split; trivial Railway deploy |
| Repo | public `RanHassid17/funneliq` | Own commit history as a portfolio artifact |
| Agents | real CrewAI package, shipped in the repo | Part of the product (the "ask a question" surface), not just build scaffolding |
| Deploy | Railway, auto-deploy from GitHub | Required by brief |
| Auth | Supabase Auth, email + password | Required by brief |
| Charts | server-rendered PNGs into `reports/` **and** a light client chart lib | Committed PNGs are evidence; the dashboard stays interactive |
| Seeds | fixed `RANDOM_SEED = 42`, recorded with the git SHA in every metrics file | Reproducibility (Brief §07) |

Free tiers only (Supabase + Railway). The 207 KB source CSV is tracked in `data/` — it is
synthetic and small, and tracking it makes the repo reproducible. This is not the "data dump"
the brief's `.gitignore` rule targets; the README says so explicitly.

---

## 4. Architecture

```
Browser (index.html = login, dashboard.html)
  └─ supabase-js ── ANON KEY ONLY ──────────► Supabase Auth
  └─ fetch(Bearer JWT) ─────────────────────► FastAPI on Railway
                                                ├─ verifies Supabase JWT server-side
                                                ├─ models/*.pkl → campaign predictions
                                                ├─ Supabase client (SERVICE KEY,
                                                │    server-side only) ──► Postgres + RLS
                                                └─ crew/ → CrewAI campaign analyst
```

The anon-key-in-browser / service-key-on-server split is the security property the brief
actually grades. It falls out of this shape rather than being bolted on.

## 5. Repository layout

Updated in Phase 8 to what actually shipped. The version here through Phase 7 was the layout as
first planned, and it had drifted: it named `login.html` and `charts.js`, which never existed, and
split the models into one module per target when they were built as a shared pipeline. A layout
diagram that disagrees with the tree is worse than none — it is how `login.html` reached the §12
matrix and the README in the first place.

```
funneliq/
  src/funneliq/
    data/      profile.py  invariants.py  metrics.py  features.py  frames.py  load_to_supabase.py
    models/    train.py  estimators.py  baseline.py  evaluate.py  budget.py  tuning.py  registry.py
    api/       main.py  auth.py  db.py  config.py  schemas.py  predictors.py  distribution.py
               routes/{campaigns,predictions,ask}.py
    crew/      agents.py  analyst.py  tools.py  guardrails.py  run.py
  static/      index.html (login)  dashboard.html  app.js  styles.css
  sql/         schema.sql  rls_policies.sql
  tests/       test_{invariants,features,metrics,models,auth,auth_asymmetric,health,crew,
               distribution}.py  helpers.py
  data/        funnel_marketing_data.csv
  reports/     profile.json  invariants.json  models.json  budget_simulation.json
               tuning_ltv.json                            # generated evidence, committed
  docs/        DATA_DICTIONARY.md  GLOSSARY.md  OPEN_QUESTIONS.md  MODEL_CARDS.md
               PROJECT_STATE.md
  models/      *.pkl + a provenance card per model
  .github/workflows/ci.yml
  README.md  REPORT.md  PLAN.md  requirements.txt  .env.example  .gitignore  Procfile
```

Three departures from the plan, each with a reason: model cards are one `MODEL_CARDS.md` rather
than `model_cards/*.md`, because four models did not justify four files; the funnel and budget
routes sit in `predictions.py` rather than in modules of their own, since both are served by the
same model artifacts the prediction routes load; and no `*.png` was generated, because the
dashboard renders its charts client-side from the API,
so a committed image would be a second version of the same numbers waiting to go stale.

## 6. Data contract

### 6.1 `sql/schema.sql`

Typed columns, plus the four fields the Explainer (§11, §12) says the dataset is missing:

- `campaign_id text primary key` — synthesised deterministically at load (`CMP-{row_index:05d}`)
  because the CSV has no natural key. Deterministic so re-loads are idempotent.
- `campaign_start_date date null`, `campaign_end_date date null` — declared and left null.
  Present so the schema is forward-compatible; the README says why they are empty.
- `data_quality_flags text[] default '{}'` — populated by the invariant checks (§6.2), so a bad
  row is *visible in the database* rather than silently dropped.
- `referred boolean` (normalised from `Yes`/`No`), `purchased`/`upsell` boolean.
- `ltv_months numeric null`, `cumulative_profit numeric null` — nullable, never zero-filled
  (Explainer §5).
- Non-negativity as `check` constraints, so the database refuses impossible campaigns.

### 6.2 `invariants.py` — validation, not assumption

Runs the H1–H5 checks of §2.3 plus: non-negativity, `leads_answered ≤ num_leads`,
zero-denominator safety. Emits per-row flags into `data_quality_flags` and a summary to
`reports/invariants.json`. Rows are **flagged, not deleted** — except the 10 exact duplicates,
which are dropped (documented).

### 6.3 `metrics.py` — derived campaign metrics

Every ratio declares its denominator and returns `None` (never `0`, never `inf`) when the
denominator is zero. Raw counts are retained alongside rates.

| Metric | Formula |
|---|---|
| Cost per lead | `ad_budget / num_leads` |
| Budget per answered lead | `ad_budget / leads_answered` |
| Answer rate / non-answer rate | `leads_answered / num_leads`, `leads_not_answered / num_leads` |
| Stage retention N | `followup_N / leads_answered` |
| Stage-to-stage retention | `followup_N / followup_(N-1)` |
| Stage dropout | `1 −` stage-to-stage retention |
| Close rate (funnel) | `closed / followup_5` — pending H3 |
| Close rate (brief) | `closed / num_leads` — required by WP1 |
| Profit per lead | `cumulative_profit / num_leads` |
| Profit per closed outcome | `cumulative_profit / closed` |
| Return on ad spend | `cumulative_profit / ad_budget` — headline only if Q6 resolves to gross |
| Net campaign return | `cumulative_profit − ad_budget` — reported only if Q6 resolves to gross |
| Follow-up efficiency | `closed / (followup_1 + … + followup_5)` |

---

## 7. Prediction checkpoints and leakage-safe allowlists — the core of the project

The Explainer (§8) defines availability by *when the prediction happens*. `features.py` holds
one allowlist per (target, checkpoint) pair; `tests/test_features.py` asserts no disallowed
column ever reaches a model's feature matrix.

**Base availability by checkpoint:**

| Checkpoint | Available | Never available |
|---|---|---|
| C0 pre-launch | `ad_budget` only | everything else |
| C1 after lead response | + `num_leads`, `leads_answered`, `leads_not_answered`, answer rate, cost per lead | follow-ups, closes, economics, outcomes |
| C2 after follow-up 2 | + `followup_1`, `followup_2`, stage-1/2 retention | `followup_3..5`, closes, calls, CAC, LTV, profit, purchased, upsell, referred |
| C3 post-campaign | all columns | none — **explanation only, never sold as prediction** |

**Per-model policy:**

| Model | Checkpoint shipped | Excluded as leakage | Why | Naive baseline to beat |
|---|---|---|---|---|
| Campaign LTV (`ltv_months`) | **C2** | `cumulative_profit`, `upsell`, `referred`, `purchased`, `closed`, `not_closed`, `calls_to_*`, CAC | Profit and lifetime are near-substitutes (r = 0.85). CAC encodes `closed` exactly (H4). `calls_to_closed` is only known once closing is attempted | **R² 0.856** (budget-only) |
| Campaign upsell (`upsell`) | **C2** | `cumulative_profit`, `referred`, `purchased`, `ltv_months`, `closed`, `calls_to_*`, CAC | Average lifetime is not known when the outreach decision is made | majority class 58.1% |
| Campaign referral score 0–100 (`referred`) | **C1** | `ltv_months`, `upsell`, `purchased`, `cumulative_profit`, follow-ups, closes, `calls_to_*`, CAC | The brief asks for a score from *early funnel data*; C1 is the strictest honest reading | majority class 61.3% |
| Campaign profit (`cumulative_profit`) | **C0** | everything except `ad_budget` (+ historical campaign aggregates) | The budget simulator must run *before* any spend. `purchased` is excluded as an exact indicator of `profit > 0` (§2.3) | **R² 0.664** (budget-only) |

The naive baselines are not decoration. A budget-only group mean already reaches R² 0.66 and 0.86
(§2.6), so a boosted model that lands at 0.70 has bought very little. Every model card reports
*model minus baseline*, not just the model.

**Three things worth defending in an interview, all written up in `REPORT.md`:**

1. **CAC is excluded everywhere.** `CAC == floor(ad_budget / closed)` in **3,500/3,500 rows**.
   Given `ad_budget`, handing a model CAC hands it `closed`. It looks like a legitimate cost input
   and is in fact the campaign's sales result. A leakage smoke test trains LTV *with* CAC and
   reports the R² jump as the demonstration.
2. **`purchased` is excluded from the profit model,** because `purchased == 1` ⟺
   `cumulative_profit > 0` with zero exceptions (§2.3). It is the target's own sign, renamed.
3. **The brief's business rule has an unfair advantage.** WP3 suggests *"if LTV > X and CAC < Y,
   flag for outreach"* — using two fields the upsell model is denied at C2, one of which (CAC)
   encodes the sales outcome outright. The comparison is run anyway, with the asymmetry stated up
   front: the rule is scored at C3, the model at C2. Saying so *is* the answer the brief wants,
   not a caveat to bury.

**Correction to v1's expectation:** v1 predicted the C0 profit model would be near-useless. It is
not — `ad_budget` alone carries R² 0.66, because the data has a strong mid-budget regime (§2.5).
The C3 explanatory model is still built and shown beside it, to keep *"what drives profit"*
separate from *"what we can forecast before spending"*.

---

## 8. Work packages → what ships

| WP | Deliverable | Endpoint / panel | Brief questions answered in `REPORT.md` |
|---|---|---|---|
| 1 Exploration & cleaning | `reports/profile.json`, `invariants.json`, correlation vs `cumulative_profit`, `ad_budget → num_leads` shape, conversion by tier (Low ≤1500 / Mid 2000–5000 / High >5000) | `/api/campaigns/summary` panel | How many rows incomplete & handling; diminishing returns?; which tier converts best, and is that surprising? |
| 2 Campaign LTV | XGBoost + LightGBM + CatBoost, 5-fold CV, RMSE & R², importances compared across all three | `POST /api/predict/ltv` | Should `cumulative_profit` be a feature (§7); which features dominate & do models agree; strongest lever + action, in two sentences |
| 3 Campaign upsell | Same three as classifiers, imbalance handling, **stratified** 5-fold, Accuracy/Precision/Recall/F1, importances for the best, business-rule comparison | `POST /api/predict/upsell` | Why accuracy alone misleads; one feature or a combination; where the rule wins/loses |
| 4 Campaign referral score | CatBoost with a search over learning rate × depth × iterations, calibrated to 0–100 | `POST /api/predict/referral-score` + gauge | Profile of high-referral campaigns (`referred`=Yes, `upsell`=1, long `ltv_months`): revenue share and average CAC; how to spot them earlier |
| 5 Follow-up paradox | Dropout per stage, follow-up counts for campaigns that closed, chart | `/api/funnel/dropout` + chart | Which stage behaves unexpectedly; typical follow-ups for closed deals; change policy — yes/no and why |
| 6 Budget simulator | C0 profit model; simulate ₪50,000 as 1×₪50k / 10×₪5k / 33×₪1.5k, **with an in-distribution flag per scenario** | `POST /api/budget/simulate` + panel | Concentrate or spread; what to tell the founder next month |
| 7 **Campaign comparison** *(spec-required, new)* | Side-by-side of any two campaigns: funnel retention curves, derived metrics, model predictions, quality flags | `GET /api/campaigns/compare?a=&b=` + view | — |

`purchased` classification is **dropped**, with the evidence in §2.3: `purchased == 1` ⟺
`cumulative_profit > 0` in 3,500/3,500 rows, so it is the WP6 target coarsened to a sign bit, not
a separate question. Shipping it as a ~99%-accurate classifier would be exactly the inflated
result the brief warns against.

**WP6 guard rails.** `ad_budget` takes only 16 discrete values, capped at ₪20,000. The simulator
therefore:
- scores each scenario's per-campaign budget against the observed support and labels it
  `in_distribution` / `extrapolated`;
- refuses to headline the 1 × ₪50,000 result — it is 2.5× beyond any training row, and tree
  ensembles will silently return the ₪20,000 leaf value;
- reports total profit **and** ROAS per strategy, since Q6 (gross vs net) is unresolved, and
  checks whether the recommendation survives both readings.

**Expected headline answers**, from §2.5 — recorded here so Phase 3 either reproduces them or
explains the discrepancy, rather than discovering them for the first time in the write-up:
Mid tier (₪2,000–5,000) dominates every metric; leads per ₪1,000 fall ~4× from ₪500 to ₪20,000;
follow-up dropout is 21.7 → 25.7 → 18.6 → 10.4 → 29.2%, i.e. **the sales manager is wrong** —
stage 4 is the most retentive stage.

Class imbalance on `upsell` (~42% positive) and `referred` (~39% positive) is **mild**.
`scale_pos_weight` / class weights are implemented because the brief requires them, and the
write-up reports honestly that they are not the dominant lever here rather than overclaiming.

Every metric is written to `reports/*.json` with the seed and git SHA. Nothing is quoted in
`REPORT.md` that does not exist in a reports file.

---

## 9. Phases

Each phase is one feature branch → PR → merge, satisfying the git-workflow requirement
organically rather than staging a token PR at the end.

### Phase 0 — skeleton deployed (first)
`feat/skeleton` · Repo init, `.gitignore`, pinned `requirements.txt`, FastAPI `/health`,
`Procfile`, Railway linked to GitHub, CI running lint + one trivial test.
Deploy *before* there is real code — the brief's own advice, and correct: auth and deploy bugs
are far easier to debug against an empty app.
**Validation:** `curl https://<railway-url>/health` → 200; a push triggers redeploy; CI green;
**restart the Railway service and re-curl** (Brief: "confirm the deployment survives a restart").

### Phase 1 — data contract
`feat/data` · `schema.sql` (§6.1), `invariants.py` (§6.2), `profile.py`, idempotent
`load_to_supabase.py`, RLS enabled with an authenticated-read policy, `docs/DATA_DICTIONARY.md`,
`docs/GLOSSARY.md`, `docs/OPEN_QUESTIONS.md`.
**Blocking gate:** the §2.2–2.3 rules re-tested as committed code, results in
`reports/invariants.json`. They were measured during planning; Phase 1 turns that measurement
into a reproducible, version-controlled artifact.
**Validation:** Postgres row count == loaded count; re-running the loader changes nothing
(idempotent); an **unauthenticated** `select` is refused by RLS — evidenced with the actual
error, not asserted.
🔒 Security review · 🙋 Human approval before applying RLS policies.

### Phase 2 — metrics, features, EDA
`feat/eda` · `metrics.py` (§6.3), `features.py` implementing §7 as code, and WP1.
**Validation:** `pytest tests/test_features.py` asserts every allowlist holds and that no
excluded column reaches any feature matrix; `test_metrics.py` covers zero denominators.

### Phase 3 — models
`feat/models` · WP2–WP6 per §8, plus `registry.py` (model version, seed, git SHA, training-row
count, feature list, checkpoint — serialised beside every `.pkl`) and a model card per model.
**Validation:** CV metrics reproduce across two runs; the CAC and `cumulative_profit` leakage
smoke tests are run and their R² deltas recorded.

### Phase 4 — API + auth
`feat/api` then `feat/auth` · Endpoints per §8; `/api/campaigns` reads **live from Supabase**
(satisfying the runtime-read requirement); `auth.py` verifies the Supabase JWT on every
protected route. `/health` stays public; everything else is 401 without a valid token.
**Validation:** integration tests for no token / malformed token / expired token / valid token.
🔒 Security review before merge.

### Phase 5 — dashboard
`feat/dashboard` · Login, session handling, working sign-out, then panels: campaign summary,
LTV predictor, upsell scorer, referral 0–100 gauge, funnel dropout chart, budget simulator,
campaign comparison. Every label says *campaign*. Loading / error / empty states on each panel.
**Validation:** a logged-out visitor sees only the login screen; refresh preserves session;
sign-out clears it; keyboard navigation and contrast checked; no service key anywhere in
`static/` (grep asserted in CI).

### Phase 6 — CrewAI
`feat/crew` · The eight roles as real `Agent` definitions, two entry points:
- **Offline** `python -m funneliq.crew.run --stage analysis` — Planner → ML → QA → Docs, reads
  `reports/*.json`, drafts `REPORT.md` sections. No runtime cost; artifacts committed.
- **Runtime** `POST /api/ask`, auth-gated — Analyst + Reviewer with three tools
  (`query_supabase`, `run_model`, `funnel_stats`) answering campaign questions from the
  dashboard. Rate-limited, capped iterations, returns **503 with a clear message** when
  `ANTHROPIC_API_KEY` is unset so the app never hard-fails on a missing key.

This is what makes CrewAI part of the product rather than decoration: it is the founder's
"just ask it" surface. Agent prompts carry the campaign-level rule (Spec §16.9) so an agent
cannot drift into customer-level phrasing.
**Validation:** the offline crew reproduces a `REPORT.md` section from committed reports; the
runtime endpoint answers a known question and refuses cleanly without a key.

**Status: built, partially validated.** 24 tests cover the tools, guardrails, rate limiter and
the degradation path, and the whole crew instantiates against the real CrewAI API. The half that
is *not* validated is the half that costs money: no LLM call has been made, because
`ANTHROPIC_API_KEY` is unset and setting it is an ongoing-cost approval gate. So "refuses cleanly
without a key" is verified; "answers a known question" is not, and `docs/PROJECT_STATE.md` says
so rather than letting a passing test suite imply otherwise.

Two design choices worth recording. The Reviewer agent has **no tools**, so it judges whether the
analyst's answer was supported rather than going and finding a better one. And the tools take
**structured parameters, never SQL** — the crew holds the service-role key, which bypasses RLS,
so a tool that accepted a query would make prompt injection a direct database exploit.

### Phase 7 — QA & traceability
`feat/qa` · Independent pass: §12 matrix walked end to end, dashboard numbers reconciled against
direct SQL, adversarial checks (missing env vars, malformed CSV, invalid session, zero-lead
campaign, null profit).
**Validation:** every matrix row is ✅ with a named artifact, or explicitly marked not-done.

### Phase 8 — docs & polish
`feat/docs` · `README.md` (architecture, local setup, live URL, assumptions, campaign-vs-customer
scope note, credits for borrowed snippets), `REPORT.md` (every brief question from §8 answered,
every figure traceable to `reports/`), `.env.example`, final secret-placement pass.
Optional: 3–5 minute demo recording.

**Done.** Carried on `feat/qa` alongside Phase 7 rather than a separate `feat/docs` branch, so the
QA fixes and the documentation of those fixes ship in one PR instead of the second describing
behaviour the first had not yet merged.

Most of both documents already existed; Phase 8 was a gap-closing pass, and the gaps were the kind
that only appear when documentation is checked against a moving codebase:

- The README advertised **"Phase 6 of 8 complete"** while Phases 7 and 8 were committed.
- Its architecture diagram named **`login.html`**. That is the same non-existent file the §12
  matrix cited and Phase 7 corrected — fixing the matrix row had left the second instance behind,
  which is the ordinary way a documentation error survives being found.
- Neither document mentioned **`in_distribution`**, though Phase 7 had shipped it into every
  prediction response and into the analyst's `run_model` tool. A guard nobody is told about is a
  guard the caller cannot act on.
- `REPORT.md` had **no Package 7 section**. WP7 asks no analytical question, so no answer was
  missing, but a spec-required surface was shipped and unwritten.
- Its source list omitted **`reports/tuning_ltv.json`**, which the Package 2 verdict quotes for
  114 configurations — a direct contradiction of the document's own opening claim that every
  figure is traceable to a committed file.

The secret-placement pass is clean: no JWT- or `sk-ant`-shaped string is committed, `.env` is
untracked, `static/` references the service-role key only in comments explaining that it is absent,
and CI enforces all three on every push.

---

## 10. Agent system

Roles per Spec §16.2 — Project Planner, Data & ML Engineer, Backend Engineer, Frontend Engineer,
DevOps Engineer, Security & Governance Reviewer, QA & Reviewer, Documentation Agent.

**Shared state** lives in `docs/PROJECT_STATE.md` (a file, not agent memory): current milestone,
accepted decisions, active branch, artifact paths, dataset version, approved feature sets per
target, model results with provenance, unresolved errors, next checkpoint. **No secrets, ever.**

**Output contract** — every agent returns `agent`, `task_id`, `status`, `summary`, `artifacts`,
`evidence`, `assumptions`, `risks`, `next_action`. No agent may report a command, test,
migration, or deployment as successful without tool output proving it.

**Human approval gates** (Spec §16.5) — stop and ask before: applying or changing RLS policies,
any destructive migration, first production deployment, rotating credentials, exposing a new
public endpoint, major architecture change, anything creating ongoing cost. Routine local code,
tests, docs and analysis proceed without approval.

## 11. UI workflow

Per Spec's UI Delivery Workflow: Planner defines journey/route/states/acceptance → Frontend
generates or inspects the design (Stitch MCP is available in this environment; run
`doctor` before relying on it, and keep a hand-written HTML/CSS fallback since the integration is
experimental) → refactor into maintainable components → Backend wires **only documented
contracts**; generated UI may not invent endpoints or fields → Security reviews gating, session,
key placement → QA checks responsive layout, keyboard nav, labels, contrast, loading/error/empty
states. Supabase URL + **anon key only** may ever appear in a design prompt, generated file, or
screenshot.

## 12. Requirements traceability matrix

**Walked end to end in Phase 7.** Every row below was checked against a real artifact, not
recalled. Two rows were wrong when checked and are corrected here: `static/login.html` never
existed (the login screen is `static/index.html`), and the auth row cited a manual check that is
now automated. The pass also found one behavioural defect — see "Phase 7 findings" below.

| Source | Requirement | Phase | Artifact |
|---|---|---|---|
| Brief · GitHub | Public repo, professional README | 0, 8 | `README.md` |
| Brief · GitHub | Meaningful commit history, small commits | all | `git log` |
| Brief · GitHub | Feature branches + ≥1 PR | all | PR list |
| Brief · GitHub | `.gitignore` excludes secrets/venv | 0 | `.gitignore` |
| Brief · GitHub | GitHub Actions on every push | 0 | `.github/workflows/ci.yml` |
| Brief · Supabase | Table design + `schema.sql` | 1 | `sql/schema.sql` |
| Brief · Supabase | Repeatable CSV load script | 1 | `load_to_supabase.py` |
| Brief · Supabase | App reads Supabase **at runtime** | 4 | `/api/campaigns` |
| Brief · Supabase | Credentials from env vars | 0–4 | `.env.example` |
| Brief · Auth | Email+password login screen | 5 | `static/index.html` (**not** `login.html` — matrix was wrong) |
| Brief · Auth | Session: gated / reachable / sign-out clears | 5 | `test_auth.py` + manual check |
| Brief · Auth | Anon key in browser, service key server-only | 4, 5 | CI grep over `static/` |
| Brief · Auth | RLS policies enforce authenticated read | 1 | `sql/rls_policies.sql` |
| Brief · Railway | Public URL | 0 | live URL in README |
| Brief · Railway | Secrets as Railway env vars | 0 | deployment checklist |
| Brief · Railway | Push triggers redeploy | 0 | deploy log |
| Brief · Railway | Health endpoint + survives restart | 0 | `/health` + restart evidence |
| Brief · WP1–6 | Six work packages | 2, 3 | §8 table |
| Brief · WP1–6 | All "questions to answer" answered | 8 | `REPORT.md` |
| Brief · Deliverables | `REPORT.md` write-up | 8 | `REPORT.md` |
| Brief · Principles | Pinned dependencies, reproducible | 0 | `requirements.txt` |
| Brief · Principles | Leakage justified in writing | 2, 8 | §7 + `REPORT.md` |
| Explainer §5 | Invariant validation | 1 | `reports/invariants.json` |
| Explainer §6 / Spec §17.3 | Derived campaign metrics | 2 | `metrics.py` |
| Explainer §8 / Spec §17.4 | Per-checkpoint leakage policy | 2 | `features.py` + `test_features.py` |
| Explainer §11 | `campaign_id`, dates, quality flags | 1 | `sql/schema.sql` |
| Explainer §4 / Spec §17.7 | Open clarifications documented | 1 | `docs/OPEN_QUESTIONS.md` |
| Spec Appendix A | Campaign comparison | 3–5 | `/api/campaigns/compare` |
| Spec §16.9 / §17.1 | Campaign language throughout | all | QA pass, Phase 7 |
| Spec §16.6 | Shared project state, no secrets | 6 | `docs/PROJECT_STATE.md` |
| Spec §16.5 | Human approval gates honoured | 1, 4 | approval notes in state file |
| Spec §17.5 | Data dictionary, model cards, limitations | 1, 3, 8 | `docs/` |
| Spec §17.6 | Customer-level scope explicitly excluded | 8 | `README.md` |
| Spec §16.9 | Agents cannot drift to customer-level | 6 | `crew/guardrails.py` + `test_crew.py` |
| Phase 7 | Out-of-distribution inputs labelled | 7 | `api/distribution.py` + `test_distribution.py` |
| Phase 8 | Extrapolation guard documented for callers | 8 | `README.md` API section + `REPORT.md` limitations |
| Phase 8 | Campaign comparison written up | 8 | `REPORT.md` Package 7 |

### Phase 7 findings

**1. A zero-lead campaign was answered bare, and confidently.** `POST /api/predict/ltv` with
`num_leads=0` returned **33.66 months**; `/api/predict/upsell` returned **35.6%**. Neither
carried any signal that the input was unsupported. The training data contains **no campaign with
fewer than 11 leads**, and the 173 campaigns that closed nothing average **4.7 months** with an
upsell rate of exactly **0.0**. The 33.66 arises because the served LTV baseline reads only
`ad_budget` and is structurally blind to a funnel that reached nobody.

This was a live defect in a shipped product, not a hypothetical. The project had already written
the correct principle down twice — in `schemas.py` ("more useful than returning a confident number
derived from impossible input") and in `budget.py` ("presenting that as a forecast would be
fabrication") — and applied it only to the budget simulator. `api/distribution.py` generalises the
existing `in_distribution` mechanism to every prediction input. The number is still returned,
because a campaign that spent its budget and reached no one is a real thing; it is now returned
labelled, with the offending field and the observed range named. The crew's `run_model` tool
carries the same annotation, so an agent cannot quote a figure the API marks unsupported.

**2. Two row counts coexist.** `reports/profile.json` describes the raw CSV (**3,500** rows);
the database holds **3,490** after 10 exact duplicates were dropped at load. Reconciled directly
against Supabase: follow-up dropout agrees to **four decimal places** at every stage, so no
conclusion changes. `/api/funnel/dropout` now states which population it was computed on rather
than leaving a reader to reconcile it against `/ready`.

**3. Adversarial checks passed.** Missing env vars → `/health` 200, `/ready` 200 reporting
`configured: false`, `/api/config` 503, data routes 401 — no stack traces. Malformed inputs
(zero/negative/absurd budget, `answered > leads`, `followup_2 > followup_1`, missing budget) all
→ 422. Nulls in `ltv_months` (4) and `cumulative_profit` (29) survive the pipeline as nulls; no
derived column contains an infinity.

## 13. Risks

| Risk | Mitigation |
|---|---|
| **Boosting fails to beat the budget-only baseline** (R² 0.66 / 0.86) | Report the delta honestly in every model card. A model that ties its baseline is a finding, not a failure to hide |
| **The ₪2,000–5,000 sweet spot is a generator artefact, not a market fact** | `REPORT.md` labels it a hypothesis about the world and proposes a controlled budget split before ₪50,000 moves on its strength |
| **Simulator extrapolates past ₪20,000** | Per-scenario `in_distribution` flag; the 1 × ₪50k result is shown as unsupported rather than headlined |
| Q6 (gross vs net profit) stays unresolved | WP6 reports both ROAS and net return; the recommendation is checked for sign-flip under either reading |
| The 155 closed-but-unpaid campaigns distort training | Flagged in `data_quality_flags`, kept not dropped, and reported as their own segment |
| Model `.pkl` artifacts bloat the repo | Small for this dataset; commit them; revisit if size grows |
| ~~CrewAI compatibility with Python 3.13~~ | **Retired.** `crewai==1.9.3` installs and runs on 3.13.0; no runtime pin needed. The real constraint turned out to be a broken pin: 1.10–1.15 require `lancedb>=0.29.2`, which does not exist on PyPI, and fail identically on 3.12 |
| CrewAI's dependency weight | chromadb, onnxruntime, grpc and kubernetes add ~220 MB. Mitigated by importing `crewai` lazily so a load failure costs `/api/ask` and nothing else |
| Runtime LLM cost | Only `/api/ask` spends; bounded by rate limiting and an iteration cap |
| Railway free-tier sleep | Health endpoint plus documented cold-start behaviour in the README |
| Stitch MCP is experimental | Pin the version, run `doctor`, keep a hand-written HTML/CSS fallback |

## 14. Definition of done

A stranger opens the live URL, signs in, gets a **campaign** prediction, compares two campaigns,
sees the funnel and budget insights, asks the analyst a question, and reads the recommendations —
without anyone touching anything. The repo explains how it was built, how to run it, what each
column is assumed to mean, and what the models are *not* allowed to claim.

## 15. Next checkpoint

**Phase 0.** `/health` live on Railway, CI green, restart verified. ~45 minutes, and it de-risks
every phase after it.

One open question before Phase 0: **do Supabase and Railway accounts/projects already exist, or
are they being provisioned from scratch?** This is the only thing that changes Phase 0's shape.

The data-contract gate that used to sit after Phase 0 has effectively been paid down during this
revision (§2). Phase 1 now converts those measurements into committed, tested artifacts rather
than discovering them — which is why the feature policy in §7 is already specific enough to build
against.
