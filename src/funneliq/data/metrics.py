"""Derived campaign metrics.

Two rules hold throughout:

1. **Every ratio declares its denominator.** An unqualified "conversion rate" is
   how two people end up confidently quoting different numbers. Where more than
   one denominator is defensible -- close rate is the live example -- both are
   computed under distinct names.
2. **A zero denominator yields NaN, never 0 and never infinity.** A campaign that
   answered no leads has an *undefined* answer rate, not a zero one. Zero-filling
   would drag every downstream average toward a value nobody observed.

Raw counts are always retained alongside the rates, per the Prompt Specification
§17.3.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .invariants import FOLLOWUP_COLUMNS

#: Columns this module adds. Kept explicit so features.py can reason about which
#: derived metric depends on which raw column when building leakage allowlists.
DERIVED_COLUMNS: list[str] = [
    "cost_per_lead",
    "budget_per_answered_lead",
    "answer_rate",
    "non_answer_rate",
    *[f"stage_retention_{i}" for i in range(1, 6)],
    *[f"stage_to_stage_retention_{i}" for i in range(1, 6)],
    *[f"stage_dropout_{i}" for i in range(1, 6)],
    "close_rate_funnel",
    "close_rate_leads",
    "profit_per_lead",
    "profit_per_closed",
    "return_on_ad_spend",
    "net_campaign_return",
    "followup_efficiency",
]


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Element-wise division where a zero or missing denominator gives NaN.

    The whole point of this module having a helper at all: `a / 0` in pandas
    yields ``inf``, which survives a `notna()` check and then quietly poisons any
    mean computed over the column.
    """
    denom = pd.to_numeric(denominator, errors="coerce").astype("float64")
    numer = pd.to_numeric(numerator, errors="coerce").astype("float64")
    return (numer / denom.where(denom != 0)).replace([np.inf, -np.inf], np.nan)


def add_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with every derived campaign metric attached."""
    out = df.copy()

    budget = out["ad_budget"]
    leads = out["num_leads"]
    answered = out["leads_answered"]
    closed = out["closed"]
    profit = out["cumulative_profit"]
    survivors = out["followup_5"]

    # Acquisition efficiency ------------------------------------------------
    out["cost_per_lead"] = safe_divide(budget, leads)
    out["budget_per_answered_lead"] = safe_divide(budget, answered)
    out["answer_rate"] = safe_divide(answered, leads)
    out["non_answer_rate"] = safe_divide(out["leads_not_answered"], leads)

    # Follow-up survival ----------------------------------------------------
    # Stage 1's denominator is leads_answered, because only answered leads enter
    # the follow-up sequence at all. Verified: followup_1 <= leads_answered on
    # every source row.
    previous = answered
    for stage, column in enumerate(FOLLOWUP_COLUMNS, start=1):
        current = out[column]
        out[f"stage_retention_{stage}"] = safe_divide(current, answered)
        step = safe_divide(current, previous)
        out[f"stage_to_stage_retention_{stage}"] = step
        out[f"stage_dropout_{stage}"] = 1 - step
        previous = current

    # Conversion ------------------------------------------------------------
    # Two denominators, both reported. `followup_5` is the funnel-correct one --
    # closed + not_closed equals followup_5 on every source row, so stage-5
    # survivors are exactly the population that could still convert. The brief's
    # Package 1 asks for closed / num_leads, so that is kept too.
    out["close_rate_funnel"] = safe_divide(closed, survivors)
    out["close_rate_leads"] = safe_divide(closed, leads)

    # Profitability ---------------------------------------------------------
    out["profit_per_lead"] = safe_divide(profit, leads)
    out["profit_per_closed"] = safe_divide(profit, closed)
    # Both of these assume cumulative_profit is GROSS of ad spend -- an open
    # question (docs/OPEN_QUESTIONS.md Q6). If it turns out to be net, ROAS is
    # overstated and net return double-counts the spend.
    out["return_on_ad_spend"] = safe_divide(profit, budget)
    out["net_campaign_return"] = profit - budget

    # Sales effort ----------------------------------------------------------
    out["followup_efficiency"] = safe_divide(closed, out[FOLLOWUP_COLUMNS].sum(axis=1))

    return out
