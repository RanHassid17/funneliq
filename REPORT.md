# FunnelIQ — findings and recommendations

Campaign intelligence for Northbound Media. **Every row in the source data is one advertising
campaign, not one customer** — so every finding below is about campaigns, and nothing here should
be read as a statement about an individual client.

Every figure is traceable to a committed file in `reports/`. Nothing is quoted that a reader
cannot regenerate with `PYTHONPATH=src python -m funneliq.data.profile`.

Status: **Packages 1–7 complete.** Sources: `reports/profile.json`, `reports/invariants.json`,
`reports/models.json`, `reports/budget_simulation.json`, `reports/tuning_ltv.json`.

## The one-paragraph summary

`ad_budget` explains almost everything in this dataset, and it does so non-linearly: campaigns in
the **₪2,000–5,000 band massively outperform** both smaller and larger ones. Gradient boosting
**fails to beat a budget-only baseline on campaign lifetime** and only ties it on profit — an
honest negative result, and the reason baselines were mandatory. Boosting *does* earn its place on
the two classification tasks, taking upsell F1 from 0.00 to 0.70 and referral F1 to 0.72. The
budget recommendation is to **spread ₪50,000 across ~25 campaigns of ₪2,000**, with the caveat
that the effect driving it may be an artefact of how this dataset was generated.

---

## Package 1 — Exploration and cleaning

Source: `reports/profile.json`, `reports/invariants.json` · 3,500 rows × 19 columns.

### How many rows are incomplete, and how were they handled?

| Issue | Count | Treatment |
|---|---|---|
| Exact duplicate rows | 10 | **Dropped.** 3,490 loaded |
| Missing `cumulative_profit` | 29 | **Kept as NULL**, flagged `cumulative_profit_missing` |
| Missing `ltv_months` | 4 | **Kept as NULL**, flagged `ltv_months_missing` |
| Negative values | 0 | — |
| Structural violations | 0 | — |

Missing values are **never zero-filled**. "We don't know what this campaign earned" and "this
campaign earned nothing" are different facts, and 335 campaigns genuinely earned zero — merging
the two would corrupt every average. Each model drops rows missing *its own* target rather than
imputing one.

### The data is more structured than it first appears

Seven relationships hold on **3,500/3,500 rows**. Three change how the data may be modelled:

**`customer_acquisition_cost == floor(ad_budget / closed)`** (0 when nothing closed). CAC is not
an independent cost input — paired with `ad_budget` it reveals `closed` exactly. It is excluded
from every model that predicts before the sales outcome is known.

**`purchased == 1` ⟺ `cumulative_profit > 0`**, with zero exceptions. It does *not* mean "a deal
closed": **155 campaigns closed 1–8 deals yet recorded `purchased = 0`, zero profit and zero
upsell** — deals closed, nothing collected. That is a real commercial segment worth investigating
operationally, and it is why `purchased` was dropped as a modelling target: it restates the profit
target as a sign bit.

**`closed + not_closed == followup_5`.** Stage-5 survivors are exactly the population that could
still convert, which settles the close-rate denominator. Both rates are reported below.

### Does more budget buy proportionally more leads?

**No — returns diminish steeply and monotonically.**

| Budget | Mean leads | Leads per ₪1,000 |
|---|---|---|
| ₪500 | 12.9 | **25.7** |
| ₪1,500 | 25.2 | 16.8 |
| ₪3,000 | 38.6 | 12.9 |
| ₪5,000 | 52.4 | 10.5 |
| ₪10,000 | 79.6 | 8.0 |
| ₪20,000 | 121.4 | **6.1** |

The largest campaigns buy leads at **less than a quarter** the efficiency of the smallest. Lead
volume grows roughly with the square root of spend, not linearly.

Note for later: `ad_budget` takes only **16 distinct values**, capped at ₪20,000. That constrains
the Package 6 simulator — see the caveat there.

### Which budget tier converts best — and is that surprising?

**The mid tier wins on every single measure, and yes, it is surprising.**

| Tier | Campaigns | Mean LTV | Upsell | Referral | Close rate (/survivors) | Mean profit | ROAS |
|---|---|---|---|---|---|---|---|
| Low ≤ ₪1,500 | 780 | 7.9 mo | 15.6% | 7.7% | 33.3% | ₪2,291 | 2.12 |
| **Mid ₪2,000–5,000** | **1,717** | **33.6 mo** | **66.3%** | **64.2%** | **42.8%** | **₪21,792** | **6.79** |
| High > ₪5,000 | 1,003 | 13.2 mo | 20.5% | 19.1% | 29.9% | ₪5,186 | 0.52 |

Two things stand out:

1. **The High tier destroys value.** ROAS 0.52 means every ₪1 spent returns ₪0.52. Northbound's
   largest campaigns are, on this data, losing money.
2. **The gap is not marginal.** Mid-tier campaigns produce customers who stay **4× longer** than
   Low-tier ones and refer at **8× the rate**. This is a discontinuity, not a gradient.

It is surprising because the two obvious hypotheses both predict the opposite: if budget bought
quality you would expect High to win; if small campaigns were better targeted you would expect Low
to win. Instead there is a sweet spot in the middle.

### What predicts profit?

Correlation with `cumulative_profit`:

| Feature | r |
|---|---|
| `ltv_months` | **+0.846** |
| `upsell` | +0.652 |
| `closed` | +0.212 |
| `ad_budget` | **−0.207** |
| `customer_acquisition_cost` | −0.248 |
| `calls_to_closed` | **−0.546** |

**Campaigns that close easily are the valuable ones.** Campaigns closing in 1–2 calls average
~₪23,000 profit and 36-month lifetimes; those needing 6+ calls average ~₪1,800 and ~6.7 months.
Sales effort is a symptom of a weak campaign, not a cure for one.

The negative correlation with `ad_budget` is the tier effect above, not evidence that spending
less always earns more — the Low tier does worse than Mid.

### An honest caveat about all of this

The ₪2,000–5,000 sweet spot is **suspiciously clean**: a discrete 16-value budget grid with a
sharp regime change and a 10× profit gap. That pattern is more characteristic of a data generator
encoding a rule than of a market revealing one.

These findings are **correct for this dataset**. Before ₪50,000 of real money moves on their
strength, Northbound should run a controlled split — a handful of campaigns at each tier over one
month — and check the effect reproduces. Treat everything above as a strong hypothesis about the
world, not an established fact about it.

---

## Package 5 (preview) — the follow-up paradox

The dropout table belongs to Package 5, but it is reproduced here because exploration answered it
outright: the headline needed no model, only `reports/profile.json`. The full package below draws
the policy conclusion from it.

**The sales manager is wrong.** Stage-over-stage dropout across all campaigns:

| Stage | Leads remaining | Dropout from previous |
|---|---|---|
| Answered | 97,925 | — |
| Follow-up 1 | 76,635 | 21.7% |
| Follow-up 2 | 56,960 | 25.7% |
| Follow-up 3 | 46,357 | 18.6% |
| **Follow-up 4** | 41,549 | **10.4% — the most retentive stage in the funnel** |
| Follow-up 5 | 29,405 | 29.2% |

The claim was *"after the 3rd follow-up we're just wasting time."* Dropout actually **falls** at
stages 3 and 4, and stage 4 loses fewer leads than any other stage by a wide margin. Leads that
survive three follow-ups are the most committed in the pipeline, and cutting contact there would
abandon them at their most engaged.

The genuine cliff is at **stage 5** (29.2%), which is where a policy review is warranted — not
stage 3.

---

## Package 2 — Campaign lifetime (regression)

Target `ltv_months`, checkpoint **C2** (after follow-up 2), 3,486 campaigns, 14 features.
5-fold CV, fixed seed.

| Model | RMSE | R² | vs baseline |
|---|---|---|---|
| **Budget-only group mean (baseline)** | **4.70** | **0.8560** | — |
| CatBoost | 4.75 | 0.8532 | **−0.0028** |
| LightGBM | 4.86 | 0.8458 | −0.0102 |
| XGBoost | 4.89 | 0.8425 | −0.0135 |

### Should `cumulative_profit` be a feature here? No.

Profit and lifetime correlate at **r = 0.846**, and profit accrues *over* the lifetime being
predicted — it is a consequence of the target, not a cause. Including it would produce a model
that scores brilliantly offline and cannot run at all in production, where a campaign's total
profit is unknown at the moment you want its lifetime forecast.

`customer_acquisition_cost` is excluded for a subtler reason: it equals `floor(ad_budget / closed)`
exactly, so alongside `ad_budget` it hands the model the campaign's sales result.

**The leakage smoke test quantifies this.** Training the same CatBoost model with the forbidden
post-campaign columns lifts R² from **0.853 → 0.946**, an inflation of **+0.092**. That is the
concrete cost of a leak: a number 9 points better that no production system could reproduce.

### Which features dominate, and do the models agree?

**`ad_budget` dominates — but the three libraries disagree about how much:**

| Model | Top feature | Share |
|---|---|---|
| XGBoost | `ad_budget` | **95.8%** |
| CatBoost | `ad_budget` | **91.8%** |
| LightGBM | `answer_rate` | 18.8% (budget far lower) |

The disagreement is a **measurement artefact, not a modelling insight**. LightGBM's default
importance counts *splits*, which spreads credit across correlated features; XGBoost and CatBoost
report *gain*, which concentrates it on the one that actually moves predictions. Reading
LightGBM's spread as "the funnel metrics matter more" would be a mistake. On gain-based measures
the models agree completely.

### The strongest lever, in two sentences

Campaign budget band is by far the strongest lever on customer longevity: campaigns in the
₪2,000–5,000 range produce customers who stay **33.6 months on average, against 7.9 for smaller
and 13.2 for larger campaigns**. Northbound should move spend into that band rather than trying to
improve follow-up execution, which the model shows has comparatively little influence on lifetime.

### The honest headline: boosting loses here — and tuning does not save it

**No gradient-boosting model beat a budget-only group mean.** CatBoost came closest at default
settings and still lost by 0.003 R².

The obvious objection is that the defaults were untuned, so a tuned model might win. **That was
tested.** `reports/tuning_ltv.json` sweeps **114 configurations** across all three libraries —
learning rates 0.01–0.1, depths 2–8, 300–900 trees, with regularisation and subsampling — each
under the same 5-fold CV:

| | |
|---|---|
| Configurations tested | **114** |
| Configurations beating the baseline | **0** |
| Best tuned model | XGBoost, R² 0.854965 (`lr 0.01, depth 2, 900 trees, subsample 0.8`) |
| Baseline | **R² 0.855967** |
| Gap | **−0.001** |

Tuning helped — it narrowed the gap from 0.003 to 0.001 — but nothing closed it.

**The shape of the winners is the tell.** Every top configuration is shallow (depth 2–4) with a
low learning rate. The tuner's best move is to make the model *simpler*, converging toward the
group mean from below without ever reaching it. That is what it looks like when there is no
structure left to learn: `ad_budget` has 16 distinct values and drives the target almost entirely,
so a mean per budget level is close to the ceiling, and the funnel features add nothing on top.

**Recommendation: ship the baseline for LTV.** A 300-tree ensemble here buys latency, dependencies
and opacity in exchange for slightly worse accuracy. The trained CatBoost model is kept for
comparison and reproducibility, not because it is better.

One caveat on generality: this is a synthetic dataset where budget was engineered to drive the
outcome. On messier real data, boosting would more likely earn its place. The finding is about
*this* problem, not about gradient boosting in general.

---

## Package 3 — Campaign upsell (classification)

Target `upsell`, checkpoint **C2**, 3,490 campaigns, positive rate 42.0%. Stratified 5-fold CV,
class-imbalance handling on all three models.

| Model | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|
| Majority-class baseline | 0.5799 | 0.00 | **0.00** | **0.00** |
| **CatBoost** | **0.7304** | 0.6533 | **0.7640** | **0.7039** |
| LightGBM | 0.7163 | 0.6409 | 0.7401 | 0.6865 |
| XGBoost | 0.7160 | 0.6423 | 0.7319 | 0.6836 |

### Why is accuracy alone misleading here?

Because **a model that predicts "no upsell" for every campaign scores 58% accuracy** while being
completely useless — it identifies zero upsell opportunities. Its recall and F1 are both 0.

CatBoost's 73% accuracy is only 15 points above that do-nothing baseline, which sounds modest. But
its **recall of 0.764** means it finds roughly three-quarters of the campaigns that will actually
produce an upsell, which is the number the sales team would act on. For outreach targeting, recall
matters more than precision: a false positive costs one wasted call, a false negative costs the
whole upsell.

Worth stating plainly: at 42% positives this target is only **mildly imbalanced**. Imbalance
handling is implemented as the brief requires, but it is not the dominant lever on these results
and pretending otherwise would overclaim.

### Is upsell driven by one feature or a combination?

**A combination — and this is where upsell differs from LTV.** CatBoost importances:
`ad_budget` 27.9%, `num_leads` 10.6%, `cost_per_lead` 10.2%, `answer_rate` 7.9%,
`budget_per_answered_lead` 5.8%, `stage_retention_2` 5.7%.

Budget still leads but explains only about a quarter, with the rest spread across lead volume and
funnel-efficiency metrics. That is why boosting genuinely earns its place here and did not for
LTV: there is real interaction structure to learn.

### The business rule, and why the comparison is unfair

The brief suggests *"if LTV > X and CAC < Y, flag for outreach."* Both fields are **excluded from
the upsell model** — `ltv_months` is not known at C2, and `customer_acquisition_cost` encodes the
sales outcome.

So the rule holds an information advantage the model is denied. A rule scored at C3 against a
model scored at C2 is not a fair fight, and any comparison that does not say so is misleading.
Stating the asymmetry *is* the answer here. The defensible comparison is: **the model works with
what Northbound actually knows after two follow-ups; the rule needs data that only exists once the
campaign is over**, by which point the outreach decision has already passed.

---

## Package 4 — Campaign referral score (0–100)

Target `referred`, checkpoint **C1** (after lead response only), 3,490 campaigns, 6 features.
CatBoost with a 12-point hyperparameter search over learning rate × depth × iterations.

Best parameters: `learning_rate 0.03, depth 4, iterations 300`.

| | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|
| Majority-class baseline | 0.6120 | 0.00 | 0.00 | 0.00 |
| **Tuned CatBoost** | **0.7513** | 0.6420 | **0.8139** | **0.7176** |

The search was flat — the top three configurations differ by 0.002 F1, and every one of the best
used `learning_rate 0.03` with `iterations 300`. Depth barely mattered. That is consistent with a
target driven by a few strong signals rather than deep interactions.

**Scoring pipeline:** score = predicted probability × 100, served by the app. Importances:
`ad_budget` 58.5%, `cost_per_lead` 12.4%, `num_leads` 10.6%, `answer_rate` 7.0%.

> **This is a campaign score, not a person's.** It estimates the likelihood that *a campaign*
> produces at least one referral. It is never a given customer's probability of referring a
> friend — that would need customer-level data this project does not have.

### Profiling the high-value campaigns

Campaigns with `referred = Yes`, `upsell = 1` and long lifetimes are overwhelmingly concentrated
in the **₪2,000–5,000 band**, which shows a 64.2% referral rate against 7.7% (Low) and 19.1%
(High). Mean acquisition cost in that band is lower than in the High tier despite far better
outcomes — these campaigns are cheaper *and* better.

**How could Northbound spot them earlier?** The model runs at C1, using only budget and lead
response — available within days of launch, long before any deal closes. That is the practical
value: a campaign can be identified as high-referral-potential while there is still time to fund
it further.

---

## Package 5 — The follow-up paradox

Full data in the preview above. **The sales manager's claim is wrong.**

Dropout *falls* at stages 3 (18.6%) and 4 (**10.4%**, the lowest in the funnel), then spikes at
stage 5 (29.2%). Leads surviving three follow-ups are the most committed in the pipeline.

**For campaigns that closed deals**, `calls_to_closed` correlates **−0.55** with profit: campaigns
closing in 1–2 calls average ~₪23,000 profit and 36-month lifetimes, while those needing 6+ calls
average ~₪1,800 and ~6.7 months.

**Should Northbound change its follow-up policy? Yes — but not the way Sales proposed.** Cutting
after follow-up 3 would abandon leads at their single most retentive stage. The genuine cliff is
at stage 5. The deeper point is that heavy call effort predicts a *weak* campaign rather than
producing a strong one, so the lever is campaign quality up front, not persistence later.

---

## Package 6 — Budget allocation

Target `cumulative_profit`, checkpoint **C0** (pre-launch), 3,461 campaigns, **one feature**
(`ad_budget`) — because the simulator must run before any money is spent.

| Model | RMSE | R² |
|---|---|---|
| Budget-only baseline | 6,633 | 0.6488 |
| CatBoost / LightGBM / XGBoost | 6,633 | 0.6488 |

All four are **identical to four decimal places**, which is the expected result rather than a bug:
with one categorical-in-effect feature, a tree ensemble converges on exactly the group mean. There
is nothing else for it to learn.

### Simulating ₪50,000

| Strategy | Predicted total profit | ROAS | |
|---|---|---|---|
| 1 × ₪50,000 | ₪4,776 | 0.10 | ⚠️ **extrapolated — excluded** |
| 3 × ₪16,667 | ₪15,667 | 0.31 | |
| 5 × ₪10,000 | ₪25,588 | 0.51 | |
| 10 × ₪5,000 | ₪216,984 | 4.34 | |
| 17 × ₪2,941 | ₪373,501 | 7.47 | |
| **25 × ₪2,000** | **₪543,519** | **10.87** | ✅ **recommended** |
| 33 × ₪1,515 | ₪109,609 | 2.19 | |

**Spreading wins decisively, but not without limit.** The optimum is around **25 campaigns of
₪2,000**. Going further to 33 × ₪1,515 collapses ROAS from 10.9 to 2.2, because that budget falls
below the productive band.

**The ₪50,000 single-campaign scenario is excluded, not just discounted.** ₪50,000 is 2.5× the
largest budget ever observed (₪20,000). Tree ensembles cannot extrapolate — they return the
nearest leaf value and present it with full confidence. Reporting that ₪4,776 as a forecast would
be fabrication dressed as analysis, so the simulator flags it and refuses to rank it.

### What to tell the founder next month

> Stop running campaigns above ₪5,000 — they return ₪0.52 per ₪1. Split the ₪50,000 into roughly
> **25 campaigns of ₪2,000** rather than spreading evenly across all sizes. On this data that is
> the difference between ~₪5,000 and ~₪543,000 of predicted monthly profit.
>
> **Before committing the full budget, test it.** Run one month at ₪20,000 split this way against
> ₪30,000 on the current approach, and compare. The pattern is strong but it comes from a single
> historical dataset with a suspiciously clean structure.

---

## Package 7 — Campaign comparison

`GET /api/campaigns/compare?a=&b=` puts any two campaigns side by side: the stored columns, the
derived metrics from `metrics.py`, the data-quality flags, and `delta_b_minus_a` — the difference
on every metric both campaigns actually have.

The brief asks no analytical question of this package; it is a spec-required surface rather than a
finding. Two implementation choices are worth recording anyway.

**Deltas are computed server-side.** The dashboard could subtract two numbers itself, but then
every future client would re-decide which direction counts as "better" and what to do about a
missing value. One definition, computed once, keeps the API and the UI from drifting apart.

**A metric missing on either side is omitted rather than zeroed.** 29 campaigns have no
`cumulative_profit` and 4 have no `ltv_months`. Reporting a delta of `0 − 21,792` for a campaign
whose profit was never recorded would invent a finding out of a null, which is the same mistake
the loader refuses to make when it keeps those fields NULL instead of zero-filling them.

---

## Limitations

**The mid-budget effect may not be real.** A discrete 16-value budget grid with a sharp regime
change and a 10× profit gap is more characteristic of a data generator than of an advertising
market. Every recommendation above rests on it. Validate before spending.

**Two models did not beat their baselines.** LTV and profit are both better served by a budget
group mean. That is reported rather than hidden, and the baseline is what should ship.

**Unresolved definitions.** Most importantly, whether `cumulative_profit` is gross or net of ad
spend — every ROAS figure in this report depends on it. Full register in
[`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md).

**Campaign-level only.** No statement here describes an individual customer. Churn, next-best
action and personal referral likelihood require a customer table linked by `campaign_id`, which
does not exist.

**The models answer questions they have not seen, and now say so.** No training campaign has
fewer than 11 leads, and `ad_budget` takes 16 discrete values capped at ₪20,000. Phase 7 found a
zero-lead campaign being answered with a confident 33.66-month lifetime, because the served LTV
baseline reads only `ad_budget` and is structurally blind to a funnel that reached nobody — the
173 campaigns that closed nothing average 4.7 months and upsell at exactly 0.0. Every prediction
response now carries `in_distribution`, with the offending field and the observed range named when
it is false. The guard reports extrapolation; it does not remove it. A labelled number outside the
training support is still a number the data cannot vouch for.

Model provenance — features, checkpoint, seed, git SHA, row counts — is recorded in
[`docs/MODEL_CARDS.md`](docs/MODEL_CARDS.md) and `models/*.json`.
