"""Leakage-safe feature allowlists, one per (target, prediction checkpoint).

This is the module the whole project is really about. A feature is leakage if it
would not be known at the exact moment the prediction is made -- so availability
is a property of *when you ask*, not of the column.

The design is an **allowlist, not a denylist**. Denylists fail open: add a column
to the dataset and it silently joins every model. Here a column is unusable until
someone names the checkpoint at which it becomes known.

Two exclusions here are non-obvious and were established by measurement, not
intuition (see docs/DATA_DICTIONARY.md):

- `customer_acquisition_cost` equals ``floor(ad_budget / closed)`` in every row.
  Paired with `ad_budget` it reveals `closed` exactly. It reads like a cost a
  planner knows up front; it is the campaign's sales result.
- `purchased` is exactly ``cumulative_profit > 0``. It is the profit target's own
  sign, renamed.
"""

from __future__ import annotations

from enum import StrEnum

import pandas as pd


class Checkpoint(StrEnum):
    """When the prediction is made, which decides what is knowable."""

    PRE_LAUNCH = "C0"
    AFTER_LEAD_RESPONSE = "C1"
    AFTER_FOLLOWUP_2 = "C2"
    POST_CAMPAIGN = "C3"


#: Columns that become knowable at each checkpoint, cumulatively.
#:
#: `leads_not_answered` is deliberately absent even though it is known at C1:
#: answered + not_answered == num_leads on every row, so including all three
#: feeds a tree ensemble an exactly collinear column for nothing. Two of the
#: three carry the same information.
_NEWLY_AVAILABLE: dict[Checkpoint, list[str]] = {
    Checkpoint.PRE_LAUNCH: [
        "ad_budget",
    ],
    Checkpoint.AFTER_LEAD_RESPONSE: [
        "num_leads",
        "leads_answered",
        "answer_rate",
        "cost_per_lead",
        "budget_per_answered_lead",
    ],
    Checkpoint.AFTER_FOLLOWUP_2: [
        "followup_1",
        "followup_2",
        "stage_retention_1",
        "stage_retention_2",
        "stage_to_stage_retention_1",
        "stage_to_stage_retention_2",
        "stage_dropout_1",
        "stage_dropout_2",
    ],
    Checkpoint.POST_CAMPAIGN: [
        "followup_3",
        "followup_4",
        "followup_5",
        "closed",
        "not_closed",
        "calls_to_closed",
        "calls_to_not_closed",
        "customer_acquisition_cost",
        "stage_retention_3",
        "stage_retention_4",
        "stage_retention_5",
        "stage_to_stage_retention_3",
        "stage_to_stage_retention_4",
        "stage_to_stage_retention_5",
        "stage_dropout_3",
        "stage_dropout_4",
        "stage_dropout_5",
        "close_rate_funnel",
        "close_rate_leads",
        "followup_efficiency",
    ],
}

_CHECKPOINT_ORDER: list[Checkpoint] = [
    Checkpoint.PRE_LAUNCH,
    Checkpoint.AFTER_LEAD_RESPONSE,
    Checkpoint.AFTER_FOLLOWUP_2,
    Checkpoint.POST_CAMPAIGN,
]

#: Commercial outcomes. Never a feature for one another at any checkpoint before
#: C3, and at C3 the task is explanation rather than prediction.
OUTCOME_COLUMNS: list[str] = [
    "ltv_months",
    "cumulative_profit",
    "purchased",
    "upsell",
    "referred",
    "profit_per_lead",
    "profit_per_closed",
    "return_on_ad_spend",
    "net_campaign_return",
]

#: The checkpoint each shipped model is trained and served at. See PLAN.md §7.
MODEL_CHECKPOINTS: dict[str, Checkpoint] = {
    "ltv_months": Checkpoint.AFTER_FOLLOWUP_2,
    "upsell": Checkpoint.AFTER_FOLLOWUP_2,
    "referred": Checkpoint.AFTER_LEAD_RESPONSE,
    "cumulative_profit": Checkpoint.PRE_LAUNCH,
}

#: Naive baselines each model must beat to justify its complexity. Measured with
#: a 5-fold group-mean over ad_budget alone; see PLAN.md §2.6.
NAIVE_BASELINES: dict[str, str] = {
    "ltv_months": "budget-only group mean, R2 0.856",
    "cumulative_profit": "budget-only group mean, R2 0.664",
    "upsell": "majority class, 58.1% accuracy",
    "referred": "majority class, 61.3% accuracy",
}


def available_at(checkpoint: Checkpoint) -> list[str]:
    """Every column knowable at `checkpoint`, outcomes excluded."""
    columns: list[str] = []
    for step in _CHECKPOINT_ORDER:
        columns.extend(_NEWLY_AVAILABLE[step])
        if step == checkpoint:
            break
    return columns


def feature_columns(target: str, checkpoint: Checkpoint | None = None) -> list[str]:
    """The allowlist for `target`, at its shipped checkpoint unless overridden.

    Passing an explicit checkpoint is how the leakage smoke tests deliberately
    build a leaky matrix in order to measure how much the excluded columns were
    worth -- see tests and PLAN.md §7.
    """
    if target not in MODEL_CHECKPOINTS and checkpoint is None:
        raise KeyError(
            f"Unknown target {target!r}. Known targets: {sorted(MODEL_CHECKPOINTS)}. "
            "Pass an explicit checkpoint to build a matrix for an ad-hoc target."
        )
    resolved = checkpoint or MODEL_CHECKPOINTS[target]
    return [c for c in available_at(resolved) if c != target]


def forbidden_columns(target: str, checkpoint: Checkpoint | None = None) -> list[str]:
    """Everything excluded for this target -- the complement of the allowlist."""
    resolved = checkpoint or MODEL_CHECKPOINTS[target]
    allowed = set(feature_columns(target, resolved))
    everything = {c for step in _CHECKPOINT_ORDER for c in _NEWLY_AVAILABLE[step]}
    return sorted((everything | set(OUTCOME_COLUMNS)) - allowed)


def build_matrix(
    df: pd.DataFrame, target: str, checkpoint: Checkpoint | None = None
) -> pd.DataFrame:
    """Feature matrix for `target`, refusing to return anything off the allowlist.

    The assertion is the point. A silent typo in an allowlist is exactly how a
    leaked column reaches a model and inflates a metric that nobody can later
    reproduce in production.
    """
    allowed = feature_columns(target, checkpoint)
    missing = [c for c in allowed if c not in df.columns]
    if missing:
        raise KeyError(
            f"Columns missing from the frame: {missing}. "
            "Did you forget metrics.add_derived_metrics(df)?"
        )

    matrix = df[allowed]
    leaked = sorted(set(matrix.columns) & set(forbidden_columns(target, checkpoint)))
    if leaked:  # pragma: no cover - defensive; the allowlist construction prevents it
        raise AssertionError(f"Leakage: {leaked} reached the feature matrix for {target!r}")
    return matrix
