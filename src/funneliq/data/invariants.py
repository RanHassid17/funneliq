"""Structural checks on campaign rows.

Every rule here was measured against all 3,500 source rows during planning
(PLAN.md §2). This module turns those one-off measurements into reproducible,
version-controlled code, and is the gate the modelling phases depend on: two of
these checks decide which columns are legal features.

Design choices worth knowing:

- A check reports *violations*, so an empty result means the data is sound.
- Rows are flagged, never dropped. A campaign that fails a structural check is
  still a real campaign; hiding it would make the profile look better than the
  data is.
- A check that cannot be evaluated for a row (because a value is missing) counts
  as neither pass nor violation. Missing data gets its own flag rather than being
  laundered into a passing check.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

FOLLOWUP_COLUMNS: list[str] = [f"followup_{i}" for i in range(1, 6)]

#: Columns that must never be negative. Ratios are derived elsewhere; these are
#: the raw counts and amounts as they arrive from the CSV.
NON_NEGATIVE_COLUMNS: list[str] = [
    "ad_budget",
    "num_leads",
    "leads_answered",
    "leads_not_answered",
    *FOLLOWUP_COLUMNS,
    "not_closed",
    "closed",
    "calls_to_closed",
    "calls_to_not_closed",
    "customer_acquisition_cost",
    "ltv_months",
    "cumulative_profit",
]


@dataclass(frozen=True)
class Invariant:
    """A single structural rule.

    ``violations`` returns a boolean Series that is True where the row breaks the
    rule. Rows the rule cannot judge must be False, not True — see the module
    docstring on missing data.
    """

    name: str
    description: str
    violations: Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class InvariantResult:
    name: str
    description: str
    violations: int
    rows_checked: int

    @property
    def passed(self) -> bool:
        return self.violations == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "violations": self.violations,
            "rows_checked": self.rows_checked,
            "pass_rate": round(1 - self.violations / self.rows_checked, 6)
            if self.rows_checked
            else None,
            "passed": self.passed,
        }


def _expected_cac(df: pd.DataFrame) -> pd.Series:
    """CAC as the source data computes it: floor(budget / closed), 0 if nothing closed.

    Isolated into a function because this identity is the single most important
    leakage finding in the project: if it holds, then given `ad_budget`, the CAC
    column reveals `closed` exactly.
    """
    closed = df["closed"].astype("float64")
    # Guard the divide: where nothing closed there is no cost-per-acquisition to
    # compute, and the source encodes that as 0 rather than as missing.
    divisor = closed.where(closed > 0)
    return np.floor(df["ad_budget"] / divisor).fillna(0.0)


def _lead_counts_do_not_sum(df: pd.DataFrame) -> pd.Series:
    return df["leads_answered"] + df["leads_not_answered"] != df["num_leads"]


def _followups_increase(df: pd.DataFrame) -> pd.Series:
    """A later follow-up stage holding MORE leads than the one before it."""
    stages = df[FOLLOWUP_COLUMNS].to_numpy()
    increased = (np.diff(stages, axis=1) > 0).any(axis=1)
    return pd.Series(increased, index=df.index)


def _followup_1_exceeds_answered(df: pd.DataFrame) -> pd.Series:
    """More leads engaged at stage 1 than ever answered the phone."""
    return df["followup_1"] > df["leads_answered"]


def _closed_split_mismatch(df: pd.DataFrame) -> pd.Series:
    """closed + not_closed should account for exactly the stage-5 survivors.

    This is what establishes followup_5 as the funnel-correct denominator for
    close rate, rather than num_leads.
    """
    return df["closed"] + df["not_closed"] != df["followup_5"]


def _cac_mismatch(df: pd.DataFrame) -> pd.Series:
    return df["customer_acquisition_cost"].astype("float64") != _expected_cac(df)


def _purchased_profit_mismatch(df: pd.DataFrame) -> pd.Series:
    """`purchased` should be exactly the sign of `cumulative_profit`.

    Rows with missing profit cannot be judged and are not counted as violations.
    """
    profit = df["cumulative_profit"]
    mismatch = df["purchased"].astype(bool) != (profit > 0)
    return mismatch & profit.notna()


def _negative_values(df: pd.DataFrame) -> pd.Series:
    present = [c for c in NON_NEGATIVE_COLUMNS if c in df.columns]
    return (df[present] < 0).any(axis=1)


def _missing_ltv(df: pd.DataFrame) -> pd.Series:
    return df["ltv_months"].isna()


def _missing_profit(df: pd.DataFrame) -> pd.Series:
    return df["cumulative_profit"].isna()


#: Order matters only for readability of the report.
INVARIANTS: list[Invariant] = [
    Invariant(
        "lead_counts_sum",
        "leads_answered + leads_not_answered equals num_leads",
        _lead_counts_do_not_sum,
    ),
    Invariant(
        "followups_non_increasing",
        "each follow-up stage retains no more leads than the previous stage",
        _followups_increase,
    ),
    Invariant(
        "followup_1_within_answered",
        "followup_1 does not exceed leads_answered",
        _followup_1_exceeds_answered,
    ),
    Invariant(
        "closed_split_matches_followup_5",
        "closed + not_closed equals followup_5",
        _closed_split_mismatch,
    ),
    Invariant(
        "cac_matches_budget_per_closed",
        "customer_acquisition_cost equals floor(ad_budget / closed), or 0 when nothing closed",
        _cac_mismatch,
    ),
    Invariant(
        "purchased_matches_profit_sign",
        "purchased is true exactly when cumulative_profit > 0",
        _purchased_profit_mismatch,
    ),
    Invariant(
        "non_negative_values",
        "no count or amount column is negative",
        _negative_values,
    ),
    # Named for the condition the flag asserts about the ROW, not for the rule.
    # A row tagged `cumulative_profit_missing` is missing profit -- the obvious
    # reading. Naming these after the rule ("..._present") produced flags that
    # meant the opposite of what they said when read off a database row.
    Invariant(
        "ltv_months_missing",
        "ltv_months is missing",
        _missing_ltv,
    ),
    Invariant(
        "cumulative_profit_missing",
        "cumulative_profit is missing",
        _missing_profit,
    ),
]


@dataclass(frozen=True)
class InvariantReport:
    """Per-row flags plus a per-rule summary."""

    results: list[InvariantResult]
    flags: pd.Series

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": int(len(self.flags)),
            "rows_with_flags": int((self.flags.str.len() > 0).sum()),
            "all_passed": self.all_passed,
            "invariants": [r.to_dict() for r in self.results],
        }


def evaluate(df: pd.DataFrame) -> InvariantReport:
    """Run every invariant, returning per-row flags and a summary."""
    results: list[InvariantResult] = []
    flags = pd.Series([[] for _ in range(len(df))], index=df.index, dtype="object")

    for invariant in INVARIANTS:
        violated = invariant.violations(df).fillna(False).astype(bool)
        results.append(
            InvariantResult(
                name=invariant.name,
                description=invariant.description,
                violations=int(violated.sum()),
                rows_checked=int(len(df)),
            )
        )
        for idx in df.index[violated]:
            flags.at[idx] = [*flags.at[idx], invariant.name]

    return InvariantReport(results=results, flags=flags)


def write_report(report: InvariantReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
