"""The leakage policy, enforced.

These tests exist so that a leaked column breaks CI rather than quietly
inflating a metric nobody can reproduce in production. The named exclusions
(`customer_acquisition_cost`, `purchased`) get their own tests because each one
was established by measuring the data, not by intuition, and a future
contributor who does not know that would reasonably assume they are fine.
"""

from __future__ import annotations

import pandas as pd
import pytest

from funneliq.data.features import (
    MODEL_CHECKPOINTS,
    OUTCOME_COLUMNS,
    Checkpoint,
    available_at,
    build_matrix,
    feature_columns,
    forbidden_columns,
)
from funneliq.data.metrics import add_derived_metrics
from funneliq.data.profile import load_raw


@pytest.fixture(scope="module")
def enriched() -> pd.DataFrame:
    return add_derived_metrics(load_raw())


# --- Checkpoint structure ---------------------------------------------------


def test_pre_launch_knows_only_the_budget() -> None:
    """Before launch nothing has happened yet. Only the planned spend exists."""
    assert available_at(Checkpoint.PRE_LAUNCH) == ["ad_budget"]


def test_checkpoints_are_cumulative() -> None:
    previous: set[str] = set()
    for checkpoint in Checkpoint:
        current = set(available_at(checkpoint))
        assert previous <= current, f"{checkpoint} lost columns available earlier"
        previous = current


def test_no_outcome_is_ever_available_as_a_feature() -> None:
    """Outcomes are targets. They never appear on any checkpoint's availability list."""
    for checkpoint in Checkpoint:
        overlap = set(available_at(checkpoint)) & set(OUTCOME_COLUMNS)
        assert overlap == set(), f"{checkpoint} exposes outcomes {sorted(overlap)}"


def test_leads_not_answered_is_excluded_as_exactly_redundant() -> None:
    """answered + not_answered == num_leads, so the third column adds nothing."""
    assert "leads_not_answered" not in available_at(Checkpoint.POST_CAMPAIGN)


# --- The two measured exclusions --------------------------------------------


@pytest.mark.parametrize("target", sorted(MODEL_CHECKPOINTS))
def test_cac_never_reaches_a_pre_outcome_model(target: str) -> None:
    """CAC == floor(ad_budget / closed), so with ad_budget it reveals `closed`."""
    assert "customer_acquisition_cost" not in feature_columns(target)


@pytest.mark.parametrize("target", sorted(MODEL_CHECKPOINTS))
def test_purchased_never_reaches_a_model(target: str) -> None:
    """`purchased` is exactly `cumulative_profit > 0` -- the profit target's sign."""
    assert "purchased" not in feature_columns(target)


def test_cac_is_available_for_post_campaign_explanation() -> None:
    """C3 is explanation, not prediction, so the excluded columns become legal there."""
    assert "customer_acquisition_cost" in available_at(Checkpoint.POST_CAMPAIGN)


# --- Per-model allowlists ---------------------------------------------------


def test_profit_model_sees_only_the_budget() -> None:
    """The simulator must run before any spend, so it gets one feature. By design."""
    assert feature_columns("cumulative_profit") == ["ad_budget"]


def test_ltv_model_excludes_profit_and_later_outcomes() -> None:
    excluded = forbidden_columns("ltv_months")

    for column in ("cumulative_profit", "upsell", "referred", "closed", "calls_to_closed"):
        assert column in excluded


def test_upsell_model_excludes_lifetime() -> None:
    """Average lifetime is not known when the outreach decision is made."""
    assert "ltv_months" in forbidden_columns("upsell")


def test_referral_model_sees_only_early_funnel() -> None:
    """The brief asks for a score from early funnel data; C1 is the strict reading."""
    allowed = feature_columns("referred")

    assert MODEL_CHECKPOINTS["referred"] == Checkpoint.AFTER_LEAD_RESPONSE
    assert not any(c.startswith("followup_") for c in allowed)


def test_target_is_never_its_own_feature() -> None:
    for target in MODEL_CHECKPOINTS:
        assert target not in feature_columns(target)


# --- Matrix construction ----------------------------------------------------


@pytest.mark.parametrize("target", sorted(MODEL_CHECKPOINTS))
def test_build_matrix_returns_only_allowed_columns(enriched: pd.DataFrame, target: str) -> None:
    matrix = build_matrix(enriched, target)

    assert list(matrix.columns) == feature_columns(target)
    assert set(matrix.columns).isdisjoint(forbidden_columns(target))
    assert len(matrix) == len(enriched)


def test_build_matrix_reports_missing_derived_columns(enriched: pd.DataFrame) -> None:
    """A frame that skipped add_derived_metrics should fail loudly, not silently."""
    with pytest.raises(KeyError, match="add_derived_metrics"):
        build_matrix(load_raw(), "ltv_months")


def test_unknown_target_is_rejected() -> None:
    with pytest.raises(KeyError, match="Unknown target"):
        feature_columns("churn_probability")


def test_explicit_checkpoint_enables_the_leakage_smoke_test(enriched: pd.DataFrame) -> None:
    """Overriding the checkpoint is how we measure what the exclusions were worth."""
    honest = build_matrix(enriched, "ltv_months")
    leaky = build_matrix(enriched, "ltv_months", Checkpoint.POST_CAMPAIGN)

    assert "customer_acquisition_cost" not in honest.columns
    assert "customer_acquisition_cost" in leaky.columns
