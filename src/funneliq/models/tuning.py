"""Hyperparameter sweep for the campaign-lifetime regression.

Exists to answer one question honestly. Phase 3 reported that gradient boosting
loses to a budget-only group mean on `ltv_months` -- but it compared *untuned*
models against that baseline, which makes "boosting cannot beat it" a stronger
claim than the evidence supported. A tuned model might have closed the gap.

This module tests that properly: 114 configurations across all three libraries,
each under the same 5-fold CV as the baseline. The grid deliberately includes
very shallow trees (depth 2-3) and low learning rates, because a target driven by
one near-categorical feature is exactly the case where a deep model overfits
noise rather than finding structure.

Slow (~5 minutes) and deliberately NOT part of `funneliq.models.train`. It answers
a question about the modelling approach, not something that needs re-running on
every training pass.

Run:  PYTHONPATH=src python -m funneliq.models.tuning
Writes: reports/tuning_ltv.json
"""

from __future__ import annotations

import itertools
import json
import time
from collections.abc import Iterator
from typing import Any

from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

from ..data.features import build_matrix
from . import RANDOM_SEED, REPORTS_DIR
from .evaluate import budget_group_mean_baseline, regression_cv

TARGET = "ltv_months"


def _catboost_grid() -> Iterator[tuple[str, dict[str, Any]]]:
    for lr, depth, iterations, l2 in itertools.product(
        [0.01, 0.03, 0.1], [2, 4, 6, 8], [300, 900], [3.0, 10.0]
    ):
        yield (
            "catboost",
            {
                "learning_rate": lr,
                "depth": depth,
                "iterations": iterations,
                "l2_leaf_reg": l2,
            },
        )


def _xgboost_grid() -> Iterator[tuple[str, dict[str, Any]]]:
    for lr, max_depth, n_estimators, subsample in itertools.product(
        [0.01, 0.05, 0.1], [2, 3, 5, 8], [300, 900], [0.8, 1.0]
    ):
        yield (
            "xgboost",
            {
                "learning_rate": lr,
                "max_depth": max_depth,
                "n_estimators": n_estimators,
                "subsample": subsample,
            },
        )


def _lightgbm_grid() -> Iterator[tuple[str, dict[str, Any]]]:
    for lr, num_leaves, n_estimators in itertools.product(
        [0.01, 0.05, 0.1], [7, 15, 31], [300, 900]
    ):
        yield (
            "lightgbm",
            {"learning_rate": lr, "num_leaves": num_leaves, "n_estimators": n_estimators},
        )


def build(algorithm: str, params: dict[str, Any]) -> Any:
    """Instantiate one configuration with the shared seed."""
    if algorithm == "catboost":
        return CatBoostRegressor(**params, random_seed=RANDOM_SEED, verbose=0)
    if algorithm == "xgboost":
        return XGBRegressor(**params, random_state=RANDOM_SEED, n_jobs=4)
    if algorithm == "lightgbm":
        return LGBMRegressor(**params, random_state=RANDOM_SEED, verbose=-1, n_jobs=4)
    raise ValueError(f"Unknown algorithm {algorithm!r}")


def sweep() -> dict[str, Any]:
    from .train import load_frame

    df = load_frame()
    frame = df[df[TARGET].notna()]
    X = build_matrix(frame, TARGET)
    y = frame[TARGET].astype("float64")

    baseline = budget_group_mean_baseline(frame["ad_budget"], y)
    baseline_r2 = baseline.metrics["r2"]
    print(f"{len(frame)} rows, {X.shape[1]} features")
    print(f"Baseline (budget group mean): R2 {baseline_r2:.6f}\n")

    started = time.time()
    results: list[dict[str, Any]] = []
    grids = [*_catboost_grid(), *_xgboost_grid(), *_lightgbm_grid()]

    for index, (algorithm, params) in enumerate(grids, start=1):
        scored = regression_cv(algorithm, lambda a=algorithm, p=params: build(a, p), X, y)
        results.append(
            {
                "algorithm": algorithm,
                "params": params,
                "r2": round(scored.metrics["r2"], 6),
                "rmse": round(scored.metrics["rmse"], 4),
                "delta_r2_vs_baseline": round(scored.metrics["r2"] - baseline_r2, 6),
                "beats_baseline": scored.metrics["r2"] > baseline_r2,
            }
        )
        if index % 20 == 0:
            print(f"  {index}/{len(grids)} configs ({time.time() - started:.0f}s)")

    results.sort(key=lambda r: -r["r2"])
    winners = [r for r in results if r["beats_baseline"]]

    return {
        "target": TARGET,
        "question": "Does a tuned gradient-boosting model beat the budget-only baseline?",
        "seed": RANDOM_SEED,
        "rows": len(frame),
        "features": list(X.columns),
        "baseline": baseline.to_dict(),
        "configs_tested": len(results),
        "configs_beating_baseline": len(winners),
        "elapsed_seconds": round(time.time() - started, 1),
        "best": results[0],
        "top_10": results[:10],
    }


def main() -> None:
    result = sweep()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORTS_DIR / "tuning_ltv.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"\nWrote {output}")
    print(f"Configurations tested: {result['configs_tested']}")
    print(f"Configurations beating the baseline: {result['configs_beating_baseline']}")
    best = result["best"]
    print(
        f"Best: {best['algorithm']} R2 {best['r2']:.6f} "
        f"(delta {best['delta_r2_vs_baseline']:+.6f}) {best['params']}"
    )


if __name__ == "__main__":
    main()
