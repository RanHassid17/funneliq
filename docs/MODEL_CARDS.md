# Model cards

Four campaign models. Machine-readable provenance for each lives beside its artifact in
`models/<name>.json`; full evaluation results are in `reports/models.json`.

**Every model here predicts a property of a campaign.** None describes an individual customer.

Shared: seed `42`, 5-fold CV (stratified for classification), rows missing a model's own target are
dropped rather than imputed, and every model is reported against a naive baseline.

---

## 1. `ltv_months` — campaign lifetime

| | |
|---|---|
| Target | `ltv_months` — **average** lifetime of the customers a campaign produced |
| Checkpoint | **C2** — after follow-up 2 |
| Features | 14 (budget, lead counts, answer rate, follow-ups 1–2 and their retention rates) |
| Rows trained | 3,486 |
| Algorithm | CatBoost (best of three) |
| **CV** | **RMSE 4.75 · R² 0.8532** |
| Baseline | Budget-only group mean — RMSE 4.70 · **R² 0.8560** |
| **vs baseline** | **−0.0028 R² — the model LOSES** |

### ⚠️ Do not deploy this model. Ship the baseline.

Gradient boosting did not beat a group mean over `ad_budget`. This is not a tuning failure:
`ad_budget` has 16 distinct values and drives the target almost entirely, so a group mean over
those 16 categories is already near-optimal. The funnel features add nothing on top.

A 300-tree ensemble here buys latency, dependencies and opacity in exchange for slightly worse
accuracy. The artifact is kept for reproducibility and comparison, not for production.

**Excluded as leakage:** `cumulative_profit` (r = 0.846 with the target, and accrues *over* the
lifetime being predicted), `customer_acquisition_cost` (equals `floor(ad_budget / closed)`, so it
encodes the sales outcome), plus `upsell`, `referred`, `closed`, `not_closed`, `calls_to_*`.

**Leakage smoke test:** re-training with the forbidden post-campaign columns lifts R² to
**0.9456** (+0.092). That gap is what a leak buys you offline and cannot deliver in production.

---

## 2. `upsell` — campaign upsell likelihood

| | |
|---|---|
| Target | `upsell` — campaign produced at least one upsell (assumed definition) |
| Checkpoint | **C2** — after follow-up 2 |
| Features | 14 |
| Rows trained | 3,490 · positive rate **42.0%** |
| Algorithm | CatBoost (best of three by F1) |
| **CV** | **Accuracy 0.7304 · Precision 0.6533 · Recall 0.7640 · F1 0.7039** |
| Baseline | Majority class — Accuracy 0.5799 · **F1 0.00 · Recall 0.00** |
| **vs baseline** | **+0.704 F1 · +0.150 accuracy** |

### ✅ Deploy. This one earns its complexity.

Unlike LTV, importances are genuinely spread — `ad_budget` 27.9%, `num_leads` 10.6%,
`cost_per_lead` 10.2%, `answer_rate` 7.9% — so there is real interaction structure for boosting to
learn.

**Read recall, not accuracy.** A do-nothing model scores 58% accuracy with zero recall. Recall
0.764 means the model finds roughly three-quarters of campaigns that will produce an upsell, and
for outreach targeting a false negative (a missed upsell) costs far more than a false positive (a
wasted call).

**Imbalance handling** is implemented per library (`scale_pos_weight`, `class_weight="balanced"`,
`auto_class_weights`) as the brief requires. Honestly: at 42% positives this target is only mildly
imbalanced and the handling is not the dominant lever on these results.

**Excluded as leakage:** `ltv_months` (not known when the outreach decision is made),
`cumulative_profit`, `referred`, `purchased`, `customer_acquisition_cost`.

---

## 3. `referral_score` — campaign referral likelihood, 0–100

| | |
|---|---|
| Target | `referred` — campaign produced at least one referral (assumed definition) |
| Checkpoint | **C1** — after lead response only |
| Features | 6 (`ad_budget`, `num_leads`, `leads_answered`, `answer_rate`, `cost_per_lead`, `budget_per_answered_lead`) |
| Rows trained | 3,490 |
| Algorithm | CatBoost, tuned — `learning_rate 0.03, depth 4, iterations 300` (12-point search) |
| **CV** | **Accuracy 0.7513 · Precision 0.6420 · Recall 0.8139 · F1 0.7176** |
| Baseline | Majority class — Accuracy 0.6120 · **F1 0.00** |
| **vs baseline** | **+0.718 F1 · +0.139 accuracy** |

### ✅ Deploy. Score = predicted probability × 100.

> **This is a campaign score, not a person's.** It estimates the chance that *a campaign* produces
> at least one referral. It must never be labelled as a customer's probability of referring a
> friend. Individual referral prediction needs a customer-level table linked by `campaign_id`,
> which does not exist.

**Why C1?** The brief asks for a score from *early funnel data*. C1 is the strictest honest
reading: budget and lead response only, available within days of launch and long before any deal
closes. That is the practical value — a promising campaign can be identified while there is still
time to fund it further.

**Tuning was flat.** The top three configurations differ by 0.002 F1 and all used
`learning_rate 0.03, iterations 300`; depth barely mattered. Consistent with a target driven by a
few strong signals rather than deep interactions.

Importances: `ad_budget` 58.5%, `cost_per_lead` 12.4%, `num_leads` 10.6%, `answer_rate` 7.0%.

---

## 4. `cumulative_profit` — campaign profit, pre-launch

| | |
|---|---|
| Target | `cumulative_profit` — **total** profit attributed to the campaign |
| Checkpoint | **C0** — pre-launch |
| Features | **1** — `ad_budget` |
| Rows trained | 3,461 |
| Algorithm | CatBoost |
| **CV** | **RMSE 6,632.8 · R² 0.6488** |
| Baseline | Budget-only group mean — RMSE 6,633.2 · R² 0.6488 |
| **vs baseline** | **+0.00005 R² — an exact tie** |

### ⚠️ Ties the baseline. Either is fine; prefer the baseline.

All three libraries returned identical scores to four decimal places. That is the expected result,
not a bug: with one effectively-categorical feature a tree ensemble converges on precisely the
group mean.

**One feature is deliberate.** The budget simulator must run *before* any spend, so nothing about
the campaign's execution is knowable. `purchased` is additionally excluded because it equals
`cumulative_profit > 0` exactly — the target's own sign.

**Extrapolation limit — the important one.** Training budgets span ₪500–20,000 across 16 discrete
values. Tree ensembles cannot extrapolate: asked about ₪50,000 they return the ₪20,000 leaf value
with full apparent confidence. The simulator (`models/budget.py`) therefore labels every scenario
`in_distribution` or `extrapolated` and **excludes extrapolated scenarios from the
recommendation** rather than ranking them.

---

## Limitations shared by all four

**The mid-budget regime may be an artefact.** Every model leans on `ad_budget`, and the
₪2,000–5,000 band outperforms so cleanly that it looks more like a generator rule than a market
effect. Validate with a controlled budget split before acting on any of these at scale.

**Gross vs net profit is unresolved** (`docs/OPEN_QUESTIONS.md` Q6). Every ROAS figure derived
from these models depends on `cumulative_profit` being gross of ad spend, which is assumed and
unconfirmed.

**Target definitions are assumed.** `upsell` and `referred` are read as "at least one occurred".
No test in the data can distinguish that from alternative definitions.

**Campaign-level only.** Churn, next-best-action, personalised follow-up and individual referral
prediction are out of scope until customer-level data exists.

**Retraining:** `PYTHONPATH=src python -m funneliq.models.train`, then
`PYTHONPATH=src python -m funneliq.models.budget`. Both are deterministic under seed 42.
