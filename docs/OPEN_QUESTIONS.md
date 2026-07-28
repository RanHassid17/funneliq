# Open questions and assumptions

The Dataset Explainer (§4) and Prompt Specification (§17.7) require these to be confirmed with the
data owner before final modelling. There is no reachable data owner on this project, so each one
becomes a **documented, tested assumption** rather than a silent one.

Where the data itself could settle a question, it was asked of all 3,500 rows. Four were resolved
that way — one of them by refuting the obvious reading.

Status legend: **Resolved** = settled by evidence · **Assumed** = no test available, documented and
carried

---

## Resolved by evidence

### Q2 — Is `closed` customers, deals, or completed calls? · **Resolved**

`customer_acquisition_cost == floor(ad_budget / closed)` on 3,500/3,500 rows. A cost *per acquired
customer* computed with `closed` as the divisor means `closed` is the acquired-customer count.

*Test:* `cac_matches_budget_per_closed`

### Q4 — Does `purchased = 1` mean at least one purchase? · **Resolved — and refuted**

**No.** `purchased == 1` ⟺ `cumulative_profit > 0`, exactly, zero off-diagonal rows. It means the
campaign *earned revenue*.

The obvious reading — `purchased == (closed > 0)` — fails on 155 rows that closed 1–8 deals while
recording `purchased = 0`, `cumulative_profit = 0` and `upsell = 0`. Deals closed; nothing
collected.

*Consequences:* `purchased` dropped as a target; excluded from the profit model; the 155
closed-but-unpaid campaigns flagged, kept, and reported as their own segment.
*Test:* `purchased_matches_profit_sign`

### Q10 — What is the denominator for close rate? · **Resolved** *(added during Phase 1)*

`closed + not_closed == followup_5` on 3,500/3,500 rows, so the funnel-correct denominator is
`followup_5`. `closed / num_leads` is still reported because Package 1 asks for it.

*Test:* `closed_split_matches_followup_5`

### Q11 — Is `leads_answered + leads_not_answered == num_leads`? · **Resolved**

Yes, 3,500/3,500. The three columns are exactly redundant — models get two of the three, never all
three.

*Test:* `lead_counts_sum`

---

## Assumed — no test available

### Q1 — Is a row a campaign, a month, an ad set, or a lead cohort?

**Assumed:** a campaign or campaign period, per Explainer §1. No time-series modelling is done, so
campaign-versus-month does not change any result.

### Q3 — Are `calls_to_closed` / `calls_to_not_closed` totals or averages?

**Assumed:** per-outcome averages. Observed range is 0–9 across campaigns of 11–139 leads, which is
implausible as a total call count and consistent with an average. Suggestive, not conclusive.

### Q5 — Is `ltv_months` observed, estimated, or averaged?

**Assumed:** the average lifetime across the customers a campaign produced. Affects the wording of
every LTV output — never phrased as one person's tenure.

### Q6 — Is `cumulative_profit` gross or net of ad spend? · **Highest-impact open question**

**Assumed:** gross of ad spend.

If wrong, ROAS and net-campaign-return are both misstated, and the Package 6 budget recommendation
could invert. Mitigation: Package 6 reports **both** readings and checks whether the recommendation
survives either. Until resolved, ROAS is labelled as assumption-dependent wherever it appears.

### Q7 — Does `upsell = 1` mean at least one upsell?

**Assumed:** yes. No internal test distinguishes "≥1 upsell" from "all converted customers upsold".

### Q8 — Does `referred = Yes` mean at least one referral?

**Assumed:** yes. Same limitation as Q7. The 0–100 score is therefore a *campaign* referral
likelihood, never an individual's.

### Q9 — Are follow-up stages fixed in time (day 1, 3, 7, 14, 30)?

**Unknown.** Stages are treated as ordinal only; no time-based features are built.

---

## How these surface to users

Every assumption above appears in `README.md`, in the model card of any model it affects, and as a
caveat on the dashboard panel that displays it. An assumption the user cannot see is
indistinguishable from a claim.

## If an assumption is later confirmed or refuted

Record the outcome here with its date and evidence, update the affected model cards, and re-run
the invariant suite. A refuted assumption that changes a feature allowlist requires retraining
before any prediction is served.
