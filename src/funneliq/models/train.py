"""Train and evaluate every campaign model.

Packages 2, 3, 4 and 6 share one pipeline that differs only in (target,
checkpoint, estimator family). They live in this single module rather than four
near-identical files, because four copies of the same function is a maintenance
liability, not modularity.

Run:  PYTHONPATH=src python -m funneliq.models.train
Writes: reports/models.json, models/*.pkl, models/*.json
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import pandas as pd
from catboost import CatBoostClassifier

from ..data.features import MODEL_CHECKPOINTS, Checkpoint, build_matrix, feature_columns
from ..data.load_to_supabase import prepare
from ..data.metrics import add_derived_metrics
from ..data.profile import load_raw
from . import RANDOM_SEED, REPORTS_DIR
from .baseline import BudgetGroupMeanRegressor
from .estimators import classifiers, feature_importances, regressors
from .evaluate import (
    CVResult,
    budget_group_mean_baseline,
    classification_cv,
    improvement,
    majority_class_baseline,
    regression_cv,
)
from .registry import ModelCard, save


def load_frame() -> pd.DataFrame:
    """De-duplicated campaigns with derived metrics attached."""
    prepared, _ = prepare(load_raw())
    return add_derived_metrics(prepared)


def _drop_missing_target(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Drop rows missing THIS model's target -- never impute a target."""
    return df[df[target].notna()]


def train_regression(df: pd.DataFrame, target: str, package: str) -> dict[str, Any]:
    frame = _drop_missing_target(df, target)
    X = build_matrix(frame, target)
    y = frame[target].astype("float64")

    baseline = budget_group_mean_baseline(frame["ad_budget"], y)
    results = {name: regression_cv(name, factory, X, y) for name, factory in regressors().items()}

    best_name = max(results, key=lambda n: results[n].metrics["r2"])
    best = regressors()[best_name]()
    best.fit(X, y)

    card = ModelCard(
        name=target,
        target=target,
        checkpoint=str(MODEL_CHECKPOINTS[target]),
        features=list(X.columns),
        rows_trained=len(frame),
        algorithm=best_name,
        metrics=results[best_name].metrics,
        baseline_name=baseline.name,
        baseline_metrics=baseline.metrics,
        improvement={
            "r2": improvement(results[best_name], baseline, "r2"),
            "rmse": improvement(results[best_name], baseline, "rmse"),
        },
        notes=[
            f"{package}. Campaign-level target, never an individual customer's.",
            "Rows missing this target are dropped, never imputed.",
        ],
    )
    save(best, card)

    return {
        "package": package,
        "target": target,
        "checkpoint": str(MODEL_CHECKPOINTS[target]),
        "features": list(X.columns),
        "rows": len(frame),
        "baseline": baseline.to_dict(),
        "models": {n: r.to_dict() for n, r in results.items()},
        "best": best_name,
        "improvement_over_baseline": card.improvement,
        "feature_importances": {
            n: feature_importances(regressors()[n]().fit(X, y), list(X.columns)) for n in results
        },
    }


def train_classification(df: pd.DataFrame, target: str, package: str) -> dict[str, Any]:
    frame = _drop_missing_target(df, target)
    X = build_matrix(frame, target)
    y = frame[target].astype(int)

    baseline = majority_class_baseline(y)
    results = {
        name: classification_cv(name, factory, X, y) for name, factory in classifiers(y).items()
    }

    best_name = max(results, key=lambda n: results[n].metrics["f1"])
    best = classifiers(y)[best_name]()
    best.fit(X, y)

    card = ModelCard(
        name=target,
        target=target,
        checkpoint=str(MODEL_CHECKPOINTS[target]),
        features=list(X.columns),
        rows_trained=len(frame),
        algorithm=best_name,
        metrics=results[best_name].metrics,
        baseline_name=baseline.name,
        baseline_metrics=baseline.metrics,
        improvement={m: improvement(results[best_name], baseline, m) for m in ("f1", "accuracy")},
        notes=[
            f"{package}. Campaign-level outcome, not an individual's behaviour.",
            "Class imbalance handled per library; both targets are only mildly imbalanced.",
            "Accuracy alone is misleading here -- the majority baseline scores well on it "
            "while achieving zero recall on the positive class.",
        ],
    )
    save(best, card)

    return {
        "package": package,
        "target": target,
        "checkpoint": str(MODEL_CHECKPOINTS[target]),
        "features": list(X.columns),
        "rows": len(frame),
        "positive_rate": round(float(y.mean()), 6),
        "baseline": baseline.to_dict(),
        "models": {n: r.to_dict() for n, r in results.items()},
        "best": best_name,
        "improvement_over_baseline": card.improvement,
        "feature_importances": {
            best_name: feature_importances(best, list(X.columns)),
        },
    }


def tune_referral_score(df: pd.DataFrame) -> dict[str, Any]:
    """Package 4: CatBoost hyperparameter search, then a 0-100 campaign score.

    The score is the model's predicted probability times 100. It is a *campaign*
    referral likelihood -- the chance this campaign produces at least one
    referral -- and must never be presented as one customer's probability of
    referring a friend.
    """
    target = "referred"
    frame = _drop_missing_target(df, target)
    X = build_matrix(frame, target)
    y = frame[target].astype(int)

    grid = {
        "learning_rate": [0.03, 0.1],
        "depth": [4, 6, 8],
        "iterations": [300, 600],
    }
    combinations = [
        dict(zip(grid.keys(), values, strict=True)) for values in itertools.product(*grid.values())
    ]

    searched: list[dict[str, Any]] = []
    best: tuple[float, dict[str, Any], CVResult] | None = None
    for params in combinations:
        result = classification_cv(
            f"catboost_{params['learning_rate']}_{params['depth']}_{params['iterations']}",
            lambda p=params: CatBoostClassifier(
                **p,
                random_seed=RANDOM_SEED,
                auto_class_weights="Balanced",
                verbose=0,
            ),
            X,
            y,
        )
        searched.append({"params": params, "f1": round(result.metrics["f1"], 6)})
        if best is None or result.metrics["f1"] > best[0]:
            best = (result.metrics["f1"], params, result)

    assert best is not None
    _, best_params, best_result = best

    tuned = CatBoostClassifier(
        **best_params, random_seed=RANDOM_SEED, auto_class_weights="Balanced", verbose=0
    )
    tuned.fit(X, y)

    baseline = majority_class_baseline(y)
    card = ModelCard(
        name="referral_score",
        target=target,
        checkpoint=str(MODEL_CHECKPOINTS[target]),
        features=list(X.columns),
        rows_trained=len(frame),
        algorithm=f"catboost (tuned: {best_params})",
        metrics=best_result.metrics,
        baseline_name=baseline.name,
        baseline_metrics=baseline.metrics,
        improvement={m: improvement(best_result, baseline, m) for m in ("f1", "accuracy")},
        notes=[
            "Package 4. Score = predicted probability x 100, range 0-100.",
            "CAMPAIGN referral likelihood. Never an individual customer's probability.",
            "Trained at checkpoint C1 (after lead response) because the brief asks for a "
            "score from early funnel data.",
        ],
    )
    save(tuned, card)

    return {
        "package": "Package 4 - campaign referral / super-customer score",
        "target": target,
        "checkpoint": str(MODEL_CHECKPOINTS[target]),
        "features": list(X.columns),
        "rows": len(frame),
        "search_space_size": len(combinations),
        "search": sorted(searched, key=lambda s: -s["f1"]),
        "best_params": best_params,
        "best": best_result.to_dict(),
        "baseline": baseline.to_dict(),
        "improvement_over_baseline": card.improvement,
        "feature_importances": feature_importances(tuned, list(X.columns)),
    }


def leakage_smoke_test(df: pd.DataFrame) -> dict[str, Any]:
    """Measure what the excluded columns were worth.

    Trains the LTV model honestly (C2) and again with the post-campaign columns
    that the policy forbids, including `customer_acquisition_cost`. The gap is
    the concrete demonstration of why the exclusions exist: a leaky model looks
    far better offline and cannot be reproduced in production, where those
    columns do not exist yet.
    """
    target = "ltv_months"
    frame = _drop_missing_target(df, target)
    y = frame[target].astype("float64")

    honest = regression_cv("honest_C2", regressors()["catboost"], build_matrix(frame, target), y)
    leaky = regression_cv(
        "leaky_C3",
        regressors()["catboost"],
        build_matrix(frame, target, Checkpoint.POST_CAMPAIGN),
        y,
    )

    return {
        "description": "LTV model trained at its honest checkpoint versus with post-campaign "
        "columns the feature policy forbids.",
        "honest": honest.to_dict(),
        "leaky": leaky.to_dict(),
        "r2_inflation": round(leaky.metrics["r2"] - honest.metrics["r2"], 6),
        "honest_features": feature_columns(target),
        "leaked_columns": sorted(
            set(build_matrix(frame, target, Checkpoint.POST_CAMPAIGN).columns)
            - set(feature_columns(target))
        ),
    }


def save_baseline_models(df: pd.DataFrame) -> dict[str, Any]:
    """Persist the budget group-mean estimators the API actually serves.

    Gradient boosting lost to this baseline on `ltv_months` (114 tuned
    configurations, none beat it) and tied it on `cumulative_profit`, so these
    are the artifacts the app should predict from. Saving them as first-class
    models -- rather than leaving the baseline as a number in a report -- is what
    makes "ship the baseline" an implementable recommendation.
    """
    saved: dict[str, Any] = {}
    for target in ("ltv_months", "cumulative_profit"):
        frame = _drop_missing_target(df, target)
        y = frame[target].astype("float64")
        budget = frame[["ad_budget"]]

        model = BudgetGroupMeanRegressor().fit(budget, y)
        scored = budget_group_mean_baseline(frame["ad_budget"], y)

        card = ModelCard(
            name=f"{target}_baseline",
            target=target,
            checkpoint=str(MODEL_CHECKPOINTS[target]),
            features=["ad_budget"],
            rows_trained=len(frame),
            algorithm="budget_group_mean",
            metrics=scored.metrics,
            baseline_name=scored.name,
            baseline_metrics=scored.metrics,
            improvement=dict.fromkeys(scored.metrics, 0.0),
            notes=[
                "THIS is the model served in production for this target.",
                "Gradient boosting did not beat it: see reports/tuning_ltv.json.",
                "Predicts the mean outcome of campaigns sharing the same ad_budget.",
            ],
        )
        save(model, card)
        saved[target] = {
            "metrics": scored.metrics,
            "known_budgets": model.known_budgets(),
        }
    return saved


def main() -> None:
    df = load_frame()
    print(f"Loaded {len(df)} campaigns with derived metrics.")

    results: dict[str, Any] = {"seed": RANDOM_SEED, "rows": len(df)}

    print("Package 2: campaign LTV ...")
    results["package_2_ltv"] = train_regression(df, "ltv_months", "Package 2 - campaign lifetime")

    print("Package 3: campaign upsell ...")
    results["package_3_upsell"] = train_classification(df, "upsell", "Package 3 - campaign upsell")

    print("Package 4: campaign referral score (hyperparameter search) ...")
    results["package_4_referral"] = tune_referral_score(df)

    print("Package 6: campaign profit (pre-launch) ...")
    results["package_6_profit"] = train_regression(
        df, "cumulative_profit", "Package 6 - campaign profit, pre-launch"
    )

    print("Baselines the API serves ...")
    results["served_baselines"] = save_baseline_models(df)

    print("Leakage smoke test ...")
    results["leakage_smoke_test"] = leakage_smoke_test(df)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORTS_DIR / "models.json"
    output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
