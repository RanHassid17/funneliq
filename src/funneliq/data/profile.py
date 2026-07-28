"""Deterministic dataset profile.

Writes reports/profile.json. This file is the only sanctioned source for any
number quoted in README.md or REPORT.md — the rule is that nothing gets written
up unless it exists in a committed reports file, which stops plausible-sounding
statistics from drifting into the documentation.

Run:  python -m funneliq.data.profile
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from . import DATA_PATH, REPORTS_DIR
from .invariants import FOLLOWUP_COLUMNS

#: The brief's budget tiers (Package 1). Note the gap: no campaign in the source
#: data has a budget strictly between 1500 and 2000, so the tiers are exhaustive
#: in practice, but the boundaries are stated explicitly rather than assumed.
BUDGET_TIERS: list[tuple[str, float, float]] = [
    ("Low (<=1500)", 0, 1500),
    ("Mid (2000-5000)", 1500, 5000),
    ("High (>5000)", 5000, float("inf")),
]

SUMMARY_COLUMNS = [
    "ad_budget",
    "num_leads",
    "leads_answered",
    "closed",
    "calls_to_closed",
    "customer_acquisition_cost",
    "ltv_months",
    "cumulative_profit",
]


def load_raw(path: Path = DATA_PATH) -> pd.DataFrame:
    """Read the CSV exactly as delivered, with no cleaning.

    Cleaning belongs to the loader. Profiling the raw file is what lets the
    report state honestly how messy the source actually is.
    """
    return pd.read_csv(path)


def _git_sha() -> str:
    """Record which revision produced a report, so metrics stay traceable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _numeric_summary(df: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    summary: dict[str, dict[str, float | None]] = {}
    for column in SUMMARY_COLUMNS:
        series = df[column].dropna()
        summary[column] = {
            "min": float(series.min()),
            "p25": float(series.quantile(0.25)),
            "median": float(series.median()),
            "mean": round(float(series.mean()), 4),
            "p75": float(series.quantile(0.75)),
            "max": float(series.max()),
            "distinct": int(series.nunique()),
        }
    return summary


def _tier_of(budget: float) -> str:
    for label, lower, upper in BUDGET_TIERS:
        if lower < budget <= upper or (lower == 0 and budget <= upper):
            return label
    return "unclassified"


def _budget_tiers(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Package 1: conversion and economics per budget tier.

    Two close rates are reported on purpose. `closed / num_leads` is what the
    brief asks for; `closed / followup_5` is the funnel-correct one, because
    closed + not_closed accounts for exactly the stage-5 survivors. They tell
    different stories and both belong in the write-up.
    """
    tiers = df.assign(tier=df["ad_budget"].map(_tier_of))
    rows: list[dict[str, Any]] = []
    for label, _, _ in BUDGET_TIERS:
        group = tiers[tiers["tier"] == label]
        if group.empty:
            continue
        leads = int(group["num_leads"].sum())
        survivors = int(group["followup_5"].sum())
        closed = int(group["closed"].sum())
        mean_budget = float(group["ad_budget"].mean())
        mean_profit = float(group["cumulative_profit"].mean())
        rows.append(
            {
                "tier": label,
                "campaigns": int(len(group)),
                "mean_ad_budget": round(mean_budget, 2),
                "mean_ltv_months": round(float(group["ltv_months"].mean()), 4),
                "upsell_rate": round(float(group["upsell"].mean()), 4),
                "referral_rate": round(float(group["referred"].eq("Yes").mean()), 4),
                "close_rate_over_leads": round(closed / leads, 6) if leads else None,
                "close_rate_over_followup_5": round(closed / survivors, 6) if survivors else None,
                "mean_cumulative_profit": round(mean_profit, 2),
                "return_on_ad_spend": round(mean_profit / mean_budget, 4) if mean_budget else None,
            }
        )
    return rows


def _budget_efficiency(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Package 1: does more budget buy proportionally more leads?

    Leads per ₪1,000 is the diminishing-returns signal. Grouped by the discrete
    budget levels the data actually contains rather than by arbitrary bins.
    """
    grouped = df.groupby("ad_budget", observed=True)
    return [
        {
            "ad_budget": float(budget),
            "campaigns": int(len(group)),
            "mean_num_leads": round(float(group["num_leads"].mean()), 4),
            "leads_per_1000_shekels": round(float(group["num_leads"].mean()) / (budget / 1000), 4),
            "mean_cumulative_profit": round(float(group["cumulative_profit"].mean()), 2),
        }
        for budget, group in grouped
    ]


def _followup_dropout(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Package 5: stage-over-stage retention across the whole book of campaigns.

    Aggregated (sum of leads) rather than averaged per campaign, so large
    campaigns carry proportional weight. The denominator for stage 1 is
    leads_answered, since only answered leads enter the follow-up sequence.
    """
    totals = df[FOLLOWUP_COLUMNS].sum()
    previous = float(df["leads_answered"].sum())
    stages: list[dict[str, Any]] = []
    for column in FOLLOWUP_COLUMNS:
        current = float(totals[column])
        retention = current / previous if previous else None
        stages.append(
            {
                "stage": column,
                "leads_remaining": int(current),
                "retention_from_previous": round(retention, 6) if retention is not None else None,
                "dropout_from_previous": round(1 - retention, 6) if retention is not None else None,
            }
        )
        previous = current
    return stages


def _correlations(df: pd.DataFrame) -> dict[str, float]:
    """Package 1: correlation against cumulative_profit."""
    numeric = df.select_dtypes("number")
    correlations = numeric.corrwith(df["cumulative_profit"]).drop("cumulative_profit")
    return {k: round(float(v), 4) for k, v in correlations.sort_values(ascending=False).items()}


def build_profile(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "source": DATA_PATH.name,
        "git_sha": _git_sha(),
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "column_dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "missing_values": {c: int(n) for c, n in df.isna().sum().items() if n},
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "target_distributions": {
            "purchased": {str(k): int(v) for k, v in df["purchased"].value_counts().items()},
            "upsell": {str(k): int(v) for k, v in df["upsell"].value_counts().items()},
            "referred": {str(k): int(v) for k, v in df["referred"].value_counts().items()},
        },
        "numeric_summary": _numeric_summary(df),
        "correlation_with_cumulative_profit": _correlations(df),
        "budget_tiers": _budget_tiers(df),
        "budget_efficiency": _budget_efficiency(df),
        "followup_dropout": _followup_dropout(df),
    }


def main() -> None:
    df = load_raw()
    profile = build_profile(df)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORTS_DIR / "profile.json"
    output.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({profile['rows']} rows, {profile['columns']} columns)")


if __name__ == "__main__":
    main()
