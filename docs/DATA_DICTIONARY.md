# Data dictionary — `campaigns`

**One row is one advertising campaign or campaign period. Never one customer.**

Source: `data/funnel_marketing_data.csv`, 3,500 rows × 19 columns. After dropping 10 exact
duplicate rows, 3,490 campaigns are loaded. Statistics below are reproduced by
`python -m funneliq.data.profile` into `reports/profile.json`.

## Columns

| Column | Type | Meaning | Range / notes |
|---|---|---|---|
| `campaign_id` | text, PK | Synthesised at load from the source row index (`CMP-00000`…). The CSV has no key. | Deterministic, so re-loading upserts rather than duplicates |
| `campaign_start_date` | date, null | Declared for forward compatibility. | Always null — the source has no dates |
| `campaign_end_date` | date, null | As above. | Always null |
| `ad_budget` | numeric | Total campaign spend (₪). | ₪500–20,000, median ₪3,000, **only 16 distinct values** |
| `num_leads` | integer | Leads the campaign generated. | 11–139, median 40 |
| `leads_answered` | integer | Leads reached / responding. | Equals `num_leads − leads_not_answered` in every row |
| `leads_not_answered` | integer | Leads never reached. | — |
| `followup_1`…`followup_5` | integer | Leads still engaged after each follow-up round. | Non-increasing in every row; `followup_1 ≤ leads_answered` |
| `not_closed` | integer | Stage-5 survivors that did not convert. | — |
| `closed` | integer | Deals closed. | 0–9, median 3 |
| `calls_to_closed` | numeric | Call effort for closed outcomes. | 0–9. **Assumed a per-outcome average, unconfirmed** |
| `calls_to_not_closed` | numeric | Call effort for non-closed outcomes. | Same caveat |
| `customer_acquisition_cost` | numeric | Cost per acquired customer (₪). | **Derived, not independent — see below** |
| `ltv_months` | numeric, null | **Average** lifetime of the customers the campaign produced. | 1–56, median 21. 4 missing |
| `purchased` | boolean | **Campaign earned revenue** — see below. | 3,163 true / 337 false |
| `upsell` | boolean | Campaign produced ≥1 upsell (assumed). | 1,466 true / 2,034 false |
| `cumulative_profit` | numeric, null | **Total** profit attributed to the campaign (₪). | 0–149,959, median 9,035. 29 missing |
| `referred` | boolean | Campaign produced ≥1 referral (assumed). Normalised from `Yes`/`No`. | 1,354 true / 2,146 false |
| `data_quality_flags` | text[] | Invariant failures for this row. Empty means clean. | Populated at load |
| `loaded_at` | timestamptz | Load timestamp. | — |

## Three findings that change how columns may be used

### 1. `customer_acquisition_cost` is not an independent input

`CAC == floor(ad_budget / closed)`, and `0` when `closed == 0` — verified on **3,500/3,500** rows
by `cac_matches_budget_per_closed`.

Given `ad_budget`, this column reveals `closed` exactly. It looks like a cost input a planner
would know up front; it is actually the campaign's sales result. **Excluded from every model whose
prediction happens before the outcome is known.**

### 2. `purchased` is the sign of `cumulative_profit`

`purchased == 1` ⟺ `cumulative_profit > 0`, with **zero** off-diagonal rows.

It is *not* "at least one deal closed": 155 campaigns closed 1–8 deals yet have `purchased = 0`,
`cumulative_profit = 0` and `upsell = 0` — deals closed, nothing collected. Consequences:

- `purchased` is dropped as a modelling target (it restates the WP6 target as a sign bit).
- `purchased` is excluded from the profit model, and `cumulative_profit` from any `purchased` model.
- The 155 closed-but-unpaid campaigns are a real segment, flagged and kept, reported separately.

### 3. `closed + not_closed == followup_5`

Verified on 3,500/3,500 rows. The funnel-correct close-rate denominator is therefore `followup_5`,
not `num_leads`. Both are reported — the brief asks for `closed / num_leads`, and the two tell
different stories.

## Missing-value policy

`ltv_months` (4 rows) and `cumulative_profit` (29 rows) are the only columns with gaps. They are
stored as **NULL and never zero-filled**: "we do not know" and "it earned nothing" are different
facts, and conflating them corrupts every average computed downstream. Rows carry the flags
`ltv_months_present` / `cumulative_profit_present`, and each model drops rows missing *its own*
target rather than imputing one.

## Not in this dataset

No customer-level rows, no channel, platform, audience, geography, product or sales rep, no
follow-up timestamps, no separation of revenue from gross profit from net profit. Customer-level
predictions (churn, next-best-action, individual referral probability) require a future table
linked by `campaign_id` and are out of scope. See [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md).
