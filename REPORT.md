# FunnelIQ — findings and recommendations

Campaign intelligence for Northbound Media. **Every row in the source data is one advertising
campaign, not one customer** — so every finding below is about campaigns, and nothing here should
be read as a statement about an individual client.

Every figure is traceable to a committed file in `reports/`. Nothing is quoted that a reader
cannot regenerate with `PYTHONPATH=src python -m funneliq.data.profile`.

Status: **Package 1 complete.** Packages 2–6 follow in Phase 3.

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

Full analysis in Phase 3, but the headline is already unambiguous from
`reports/profile.json`.

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

## Still to come

| Package | Target | Status |
|---|---|---|
| 2 — Campaign LTV | `ltv_months` | Phase 3 |
| 3 — Campaign upsell | `upsell` | Phase 3 |
| 4 — Referral score 0–100 | `referred` | Phase 3 |
| 5 — Follow-up paradox | — | preview above |
| 6 — Budget simulator | `cumulative_profit` | Phase 3 |
| 7 — Campaign comparison | — | Phase 3–5 |

Assumptions that could not be settled from the data — most importantly whether `cumulative_profit`
is gross or net of ad spend, which affects every ROAS figure above — are tracked in
[`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md).
