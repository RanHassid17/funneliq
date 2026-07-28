# Business glossary

Canonical definitions. Where a metric has more than one defensible denominator, both are named and
the default is stated — an unqualified "conversion rate" is how two people end up arguing about
different numbers.

## Unit of analysis

**Campaign** — one advertising campaign or campaign period; one row. The unit of analysis
everywhere in FunnelIQ.

**Customer** — an individual. **FunnelIQ cannot reason about customers.** No customer-level table
exists. Any per-person claim is out of scope until one does.

## Funnel stages

| Term | Meaning |
|---|---|
| **Lead** | A prospect the campaign generated (`num_leads`) |
| **Answered lead** | A lead reached or responding (`leads_answered`) |
| **Follow-up stage N** | Leads still engaged after round N (`followup_N`), N = 1…5 |
| **Stage-5 survivor** | A lead still engaged after all five rounds. Equals `closed + not_closed` |
| **Closed** | A deal closed (`closed`) |
| **Paid campaign** | A campaign that actually earned revenue — `purchased = true`, equivalently `cumulative_profit > 0` |

## Derived metrics

Every ratio below returns **null** when its denominator is zero — never `0`, never infinity.

| Metric | Formula | Notes |
|---|---|---|
| Cost per lead | `ad_budget / num_leads` | Acquisition efficiency |
| Budget per answered lead | `ad_budget / leads_answered` | Efficiency net of unreachable traffic |
| Answer rate | `leads_answered / num_leads` | Lead quality / contactability |
| Stage retention N | `followup_N / leads_answered` | Share of answered leads surviving to stage N |
| Stage-to-stage retention | `followup_N / followup_(N−1)` | **The dropout diagnostic.** Stage 1's denominator is `leads_answered` |
| Stage dropout | `1 −` stage-to-stage retention | — |
| **Close rate (funnel)** | `closed / followup_5` | **Default.** Denominator justified by `closed + not_closed == followup_5` |
| Close rate (brief) | `closed / num_leads` | What Package 1 asks for. Reported alongside, not instead |
| Profit per lead | `cumulative_profit / num_leads` | Compares campaigns of different sizes |
| Profit per closed outcome | `cumulative_profit / closed` | Value per acquired customer |
| Return on ad spend (ROAS) | `cumulative_profit / ad_budget` | **Valid only if profit is gross of ad spend — assumed, unconfirmed** |
| Net campaign return | `cumulative_profit − ad_budget` | Same caveat |
| Follow-up efficiency | `closed / (followup_1 + … + followup_5)` | Closed deals per unit of follow-up effort |

## Budget tiers

The brief's bands (Package 1). No campaign has a budget strictly between ₪1,500 and ₪2,000, so
these are exhaustive in practice.

| Tier | Range |
|---|---|
| Low | ≤ ₪1,500 |
| Mid | ₪2,000–5,000 |
| High | > ₪5,000 |

## Prediction checkpoints

A model's checkpoint is *when* it runs, which decides what it may see. Full allowlists in
`PLAN.md` §7.

| Code | Moment | May use |
|---|---|---|
| **C0** | Before launch | `ad_budget` only |
| **C1** | After lead response | + lead counts and answer rate |
| **C2** | After follow-up 2 | + `followup_1`, `followup_2` and their retention rates |
| **C3** | Post-campaign | Everything — **explanation only, never sold as prediction** |

## Modelling terms

**Leakage** — using a feature unavailable at the moment the prediction is made. The two live
examples here are `customer_acquisition_cost` (encodes `closed`) and `purchased` (encodes the sign
of `cumulative_profit`).

**Naive baseline** — the score to beat before a model has earned its complexity. Budget-only group
means reach **R² 0.664** on `cumulative_profit` and **R² 0.856** on `ltv_months`; every model card
reports *model minus baseline*.

**Super-customer score** — a **campaign-level** 0–100 likelihood that a campaign produces
referrals. Never an individual's referral probability.
