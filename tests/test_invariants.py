"""Invariant checks, tested on synthetic rows and then on the real dataset.

The synthetic cases pin down each rule's behaviour precisely. The real-data test
is the gate the modelling phases depend on: if `cac_matches_budget_per_closed`
ever stops holding, the feature policy in PLAN.md §7 has to be revisited before
anything is trained.
"""

from __future__ import annotations

import pandas as pd
import pytest

from funneliq.data.invariants import evaluate
from funneliq.data.load_to_supabase import prepare
from funneliq.data.profile import load_raw
from helpers import make_row


def violations_for(name: str, **overrides: object) -> int:
    report = evaluate(pd.DataFrame([make_row(**overrides)]))
    return next(r.violations for r in report.results if r.name == name)


def test_clean_row_raises_no_flags() -> None:
    report = evaluate(pd.DataFrame([make_row()]))

    assert report.all_passed
    assert report.flags.iloc[0] == []


@pytest.mark.parametrize(
    ("invariant", "overrides"),
    [
        ("lead_counts_sum", {"leads_not_answered": 17}),
        ("followups_non_increasing", {"followup_3": 20}),
        ("followup_1_within_answered", {"followup_1": 33}),
        ("closed_split_matches_followup_5", {"closed": 6}),
        ("cac_matches_budget_per_closed", {"customer_acquisition_cost": 799}),
        ("non_negative_values", {"cumulative_profit": -1.0}),
        ("ltv_months_missing", {"ltv_months": None}),
        ("cumulative_profit_missing", {"cumulative_profit": None}),
    ],
)
def test_each_invariant_catches_its_own_breakage(
    invariant: str, overrides: dict[str, object]
) -> None:
    assert violations_for(invariant, **overrides) == 1


def test_cac_is_zero_when_nothing_closed() -> None:
    """Nothing closed means no cost-per-acquisition; the source encodes that as 0."""
    clean = make_row(
        closed=0, not_closed=9, customer_acquisition_cost=0, purchased=0, cumulative_profit=0.0
    )

    assert violations_for("cac_matches_budget_per_closed", **clean) == 0


def test_purchased_mismatch_is_not_raised_when_profit_is_missing() -> None:
    """A rule that cannot be evaluated must not be reported as a violation."""
    assert violations_for("purchased_matches_profit_sign", cumulative_profit=None) == 0


def test_purchased_mismatch_is_raised_when_profit_is_zero() -> None:
    assert violations_for("purchased_matches_profit_sign", cumulative_profit=0.0) == 1


def test_flags_accumulate_across_rules() -> None:
    report = evaluate(pd.DataFrame([make_row(leads_not_answered=17, followup_1=33)]))

    assert set(report.flags.iloc[0]) == {"lead_counts_sum", "followup_1_within_answered"}


# --- The real dataset -------------------------------------------------------


@pytest.fixture(scope="module")
def real_data() -> pd.DataFrame:
    return load_raw()


def test_source_dataset_shape(real_data: pd.DataFrame) -> None:
    assert real_data.shape == (3500, 19)


@pytest.mark.parametrize(
    "invariant",
    [
        "lead_counts_sum",
        "followups_non_increasing",
        "followup_1_within_answered",
        "closed_split_matches_followup_5",
        "cac_matches_budget_per_closed",
        "non_negative_values",
    ],
)
def test_structural_invariants_hold_on_every_source_row(
    real_data: pd.DataFrame, invariant: str
) -> None:
    """These held 3500/3500 during planning. Two of them decide the feature policy."""
    report = evaluate(real_data)
    result = next(r for r in report.results if r.name == invariant)

    assert result.violations == 0, f"{invariant} now fails on {result.violations} rows"


def test_purchased_is_exactly_the_sign_of_profit(real_data: pd.DataFrame) -> None:
    """Why `purchased` is dropped as a target and excluded from the profit model."""
    report = evaluate(real_data)
    result = next(r for r in report.results if r.name == "purchased_matches_profit_sign")

    assert result.violations == 0


def test_prepare_drops_exact_duplicates_and_keeps_everything_else(
    real_data: pd.DataFrame,
) -> None:
    prepared, summary = prepare(real_data)

    assert summary["exact_duplicates_dropped"] == 10
    assert summary["rows_to_load"] == 3490
    assert len(prepared) == 3490
    assert prepared["campaign_id"].is_unique


def test_prepare_normalises_outcomes_to_booleans(real_data: pd.DataFrame) -> None:
    prepared, _ = prepare(real_data)

    for column in ("referred", "purchased", "upsell"):
        assert prepared[column].dtype == bool


def test_missing_values_survive_preparation_as_nulls(real_data: pd.DataFrame) -> None:
    """Missing profit must never become zero -- that would corrupt every average."""
    prepared, _ = prepare(real_data)

    assert prepared["cumulative_profit"].isna().any()
    assert prepared["ltv_months"].isna().any()
