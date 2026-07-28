"""Model harness, registry and simulator.

Deliberately does not retrain anything -- that takes minutes and belongs in
`python -m funneliq.models.train`. What is tested here is the machinery that
decides whether a model is any good, plus the committed artifacts, which are
checked against the *current* feature policy so a policy change cannot silently
leave a stale leaky model in place.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from funneliq.data.features import MODEL_CHECKPOINTS, feature_columns, forbidden_columns
from funneliq.models import MODELS_DIR, RANDOM_SEED, REPORTS_DIR
from funneliq.models.budget import Scenario, recommend, simulate
from funneliq.models.evaluate import (
    budget_group_mean_baseline,
    improvement,
    majority_class_baseline,
)
from funneliq.models.registry import ModelCard, load, save

# --- Baselines --------------------------------------------------------------


def test_budget_baseline_predicts_group_means() -> None:
    """Two budget levels with distinct targets should be nearly perfectly separable."""
    budget = pd.Series([1000] * 50 + [5000] * 50)
    y = pd.Series([10.0] * 50 + [40.0] * 50)

    result = budget_group_mean_baseline(budget, y)

    assert result.metrics["r2"] > 0.99
    assert result.metrics["rmse"] < 1.0


def test_majority_baseline_has_zero_recall_on_the_positive_class() -> None:
    """The reason accuracy alone is a misleading headline for these targets."""
    y = pd.Series([0] * 70 + [1] * 30)

    result = majority_class_baseline(y)

    assert result.metrics["accuracy"] == pytest.approx(0.7, abs=0.05)
    assert result.metrics["recall"] == 0.0
    assert result.metrics["f1"] == 0.0


def test_improvement_is_model_minus_baseline() -> None:
    y = pd.Series([0] * 60 + [1] * 40)
    baseline = majority_class_baseline(y)

    assert improvement(baseline, baseline, "accuracy") == 0.0


# --- Registry ---------------------------------------------------------------


class Dummy:
    """Module-level so joblib can pickle it; a locally-defined class cannot be."""

    value = 42


def test_registry_roundtrip(tmp_path) -> None:
    card = ModelCard(
        name="dummy",
        target="ltv_months",
        checkpoint="C2",
        features=["ad_budget"],
        rows_trained=10,
        algorithm="none",
        metrics={"r2": 0.5},
        baseline_name="baseline",
        baseline_metrics={"r2": 0.4},
        improvement={"r2": 0.1},
    )
    save(Dummy(), card, tmp_path)
    model, loaded = load("dummy", tmp_path)

    assert model.value == 42
    assert loaded.features == ["ad_budget"]
    assert loaded.seed == RANDOM_SEED
    assert loaded.git_sha


# --- Committed model artifacts ----------------------------------------------

CARDS = sorted(MODELS_DIR.glob("*.json")) if MODELS_DIR.exists() else []


@pytest.mark.skipif(not CARDS, reason="models not built; run funneliq.models.train")
@pytest.mark.parametrize("card_path", CARDS, ids=lambda p: p.stem)
def test_saved_model_respects_the_current_feature_policy(card_path) -> None:
    """A committed model must not contain a column the policy now forbids."""
    card = json.loads(card_path.read_text())
    target = card["target"]

    leaked = set(card["features"]) & set(forbidden_columns(target))

    assert leaked == set(), f"{card_path.stem} was trained on forbidden columns {sorted(leaked)}"
    assert card["features"] == feature_columns(target)


@pytest.mark.skipif(not CARDS, reason="models not built; run funneliq.models.train")
@pytest.mark.parametrize("card_path", CARDS, ids=lambda p: p.stem)
def test_saved_model_records_its_provenance(card_path) -> None:
    card = json.loads(card_path.read_text())

    assert card["seed"] == RANDOM_SEED
    assert card["git_sha"]
    assert card["rows_trained"] > 0
    assert card["checkpoint"] == str(MODEL_CHECKPOINTS[card["target"]])


# --- Budget simulator -------------------------------------------------------


def _scenario(label: str, total: float, *, in_distribution: bool) -> Scenario:
    return Scenario(
        label=label,
        campaigns=1,
        budget_per_campaign=1.0,
        predicted_profit_per_campaign=total,
        predicted_total_profit=total,
        return_on_ad_spend=total / 50_000,
        in_distribution=in_distribution,
    )


def test_recommendation_ignores_extrapolated_scenarios() -> None:
    """An out-of-range prediction is not a weaker prediction -- it is not one."""
    scenarios = [
        _scenario("extrapolated winner", 999_999, in_distribution=False),
        _scenario("supported", 100.0, in_distribution=True),
    ]

    result = recommend(scenarios)

    assert result["recommended"]["label"] == "supported"
    assert result["excluded_as_extrapolation"] == ["extrapolated winner"]


@pytest.mark.skipif(
    not (MODELS_DIR / "cumulative_profit.pkl").exists(), reason="profit model not built"
)
def test_single_50k_campaign_is_flagged_as_extrapolation() -> None:
    """50,000 in one campaign is 2.5x the observed maximum of 20,000."""
    df = pd.DataFrame({"ad_budget": [500, 3000, 20000]})
    scenarios = simulate(df, splits=(1, 10))

    single = next(s for s in scenarios if s.campaigns == 1)
    split = next(s for s in scenarios if s.campaigns == 10)

    assert single.budget_per_campaign == 50_000
    assert not single.in_distribution
    assert split.in_distribution


def test_scenarios_always_spend_the_whole_budget() -> None:
    df = pd.DataFrame({"ad_budget": [500, 20000]})

    for scenario in simulate(df, splits=(1, 4, 10)):
        spent = scenario.budget_per_campaign * scenario.campaigns
        assert spent == pytest.approx(50_000)


# --- Committed results ------------------------------------------------------


@pytest.mark.skipif(not (REPORTS_DIR / "models.json").exists(), reason="models.json not generated")
def test_leakage_smoke_test_shows_inflation() -> None:
    """The demonstration that the excluded columns really were worth something."""
    results = json.loads((REPORTS_DIR / "models.json").read_text())
    smoke = results["leakage_smoke_test"]

    assert smoke["r2_inflation"] > 0, "leaking post-campaign columns should inflate R2"
    assert "customer_acquisition_cost" in smoke["leaked_columns"]


@pytest.mark.skipif(not (REPORTS_DIR / "models.json").exists(), reason="models.json not generated")
def test_every_package_reports_against_a_baseline() -> None:
    results = json.loads((REPORTS_DIR / "models.json").read_text())

    for key in ("package_2_ltv", "package_3_upsell", "package_4_referral", "package_6_profit"):
        assert "baseline" in results[key], f"{key} has no naive baseline to compare against"
        assert "improvement_over_baseline" in results[key]


def test_no_nan_metrics_in_reports() -> None:
    """A NaN metric is a silent failure that looks like a number in a table."""
    if not (REPORTS_DIR / "models.json").exists():
        pytest.skip("models.json not generated")
    text = (REPORTS_DIR / "models.json").read_text()

    assert "NaN" not in text
    assert not np.isnan(json.loads(text)["package_2_ltv"]["baseline"]["metrics"]["r2"])
