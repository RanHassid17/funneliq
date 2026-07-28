"""Derived metrics, with the zero-denominator cases pinned down.

The zero-denominator behaviour gets disproportionate attention here because it is
the failure that does not announce itself: `a / 0` yields ``inf`` in pandas,
survives `notna()`, and then poisons any mean taken over the column.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from funneliq.data.metrics import DERIVED_COLUMNS, add_derived_metrics, safe_divide
from funneliq.data.profile import load_raw
from helpers import make_row


@pytest.fixture(scope="module")
def enriched() -> pd.DataFrame:
    return add_derived_metrics(load_raw())


# --- safe_divide ------------------------------------------------------------


def test_safe_divide_returns_nan_for_zero_denominator() -> None:
    result = safe_divide(pd.Series([10.0]), pd.Series([0.0]))

    assert result.isna().all(), "zero denominator must be undefined, not inf"


def test_safe_divide_returns_nan_for_missing_denominator() -> None:
    assert safe_divide(pd.Series([10.0]), pd.Series([np.nan])).isna().all()


def test_safe_divide_propagates_missing_numerator() -> None:
    assert safe_divide(pd.Series([np.nan]), pd.Series([4.0])).isna().all()


def test_safe_divide_computes_normally() -> None:
    assert safe_divide(pd.Series([10.0]), pd.Series([4.0])).iloc[0] == pytest.approx(2.5)


# --- Metric definitions -----------------------------------------------------


def test_all_declared_columns_are_produced() -> None:
    result = add_derived_metrics(pd.DataFrame([make_row()]))

    for column in DERIVED_COLUMNS:
        assert column in result.columns


def test_raw_counts_are_retained() -> None:
    """Rates supplement the counts; they never replace them."""
    result = add_derived_metrics(pd.DataFrame([make_row()]))

    assert result["num_leads"].iloc[0] == 48
    assert result["closed"].iloc[0] == 5


def test_known_values() -> None:
    row = add_derived_metrics(pd.DataFrame([make_row()])).iloc[0]

    assert row["answer_rate"] == pytest.approx(32 / 48)
    assert row["cost_per_lead"] == pytest.approx(4000 / 48)
    assert row["close_rate_funnel"] == pytest.approx(5 / 9)
    assert row["close_rate_leads"] == pytest.approx(5 / 48)
    assert row["stage_retention_1"] == pytest.approx(25 / 32)
    assert row["stage_to_stage_retention_2"] == pytest.approx(18 / 25)
    assert row["stage_dropout_2"] == pytest.approx(1 - 18 / 25)
    assert row["return_on_ad_spend"] == pytest.approx(15048 / 4000)
    assert row["net_campaign_return"] == pytest.approx(15048 - 4000)


def test_stage_1_retention_is_measured_against_answered_leads() -> None:
    """Only answered leads enter the follow-up sequence, so they are the denominator."""
    row = add_derived_metrics(pd.DataFrame([make_row(leads_answered=32, followup_1=16)])).iloc[0]

    assert row["stage_to_stage_retention_1"] == pytest.approx(0.5)


def test_profit_per_closed_is_undefined_when_nothing_closed() -> None:
    row = add_derived_metrics(
        pd.DataFrame([make_row(closed=0, not_closed=9, cumulative_profit=0.0, purchased=0)])
    ).iloc[0]

    assert pd.isna(row["profit_per_closed"])
    assert row["profit_per_lead"] == pytest.approx(0.0)


def test_missing_profit_yields_missing_ratios_not_zero() -> None:
    row = add_derived_metrics(pd.DataFrame([make_row(cumulative_profit=None)])).iloc[0]

    for column in ("profit_per_lead", "profit_per_closed", "return_on_ad_spend"):
        assert pd.isna(row[column]), f"{column} must stay unknown, not become 0"


# --- Against the real dataset -----------------------------------------------


def test_no_infinities_anywhere(enriched: pd.DataFrame) -> None:
    """The failure this module exists to prevent."""
    numeric = enriched[DERIVED_COLUMNS].to_numpy(dtype="float64", na_value=np.nan)

    assert not np.isinf(numeric).any()


def test_rates_stay_within_their_natural_bounds(enriched: pd.DataFrame) -> None:
    for column in ("answer_rate", "non_answer_rate", "close_rate_funnel", "close_rate_leads"):
        values = enriched[column].dropna()
        assert values.between(0, 1).all(), f"{column} escaped [0, 1]"


def test_stage_retention_never_exceeds_one(enriched: pd.DataFrame) -> None:
    """Follow-up counts are non-increasing, so no stage can gain leads."""
    for stage in range(1, 6):
        values = enriched[f"stage_to_stage_retention_{stage}"].dropna()
        assert values.le(1).all()


def test_answer_and_non_answer_rates_sum_to_one(enriched: pd.DataFrame) -> None:
    total = enriched["answer_rate"] + enriched["non_answer_rate"]

    assert total.dropna().sub(1).abs().lt(1e-9).all()
