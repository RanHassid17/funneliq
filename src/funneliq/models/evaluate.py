"""Cross-validation harness and naive baselines.

Baselines are not decoration. A budget-only group mean already reaches R² 0.66 on
campaign profit and R² 0.86 on campaign lifetime, so a boosted model landing at
0.70 has bought almost nothing for its complexity. Every result here is reported
as *model minus baseline*, because the absolute number alone is flattering and
uninformative.

Folds are fixed by `RANDOM_SEED`, and classification uses stratified folds so a
rare class cannot vanish from a validation split.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    r2_score,
    recall_score,
    root_mean_squared_error,
)
from sklearn.model_selection import KFold, StratifiedKFold

from . import RANDOM_SEED

N_SPLITS = 5


@dataclass(frozen=True)
class CVResult:
    """Cross-validated scores for one estimator on one target."""

    name: str
    metrics: dict[str, float]
    std: dict[str, float]
    folds: list[dict[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metrics": {k: round(v, 6) for k, v in self.metrics.items()},
            "std": {k: round(v, 6) for k, v in self.std.items()},
            "folds": [{k: round(v, 6) for k, v in f.items()} for f in self.folds],
        }


def _aggregate(name: str, folds: list[dict[str, float]]) -> CVResult:
    keys = folds[0].keys()
    return CVResult(
        name=name,
        metrics={k: float(np.mean([f[k] for f in folds])) for k in keys},
        std={k: float(np.std([f[k] for f in folds])) for k in keys},
        folds=folds,
    )


def _regression_scores(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "rmse": float(root_mean_squared_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def _classification_scores(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    # zero_division=0 keeps a fold that predicts a single class from raising;
    # the resulting 0.0 is the honest score for that fold, not an error.
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }


def regression_cv(
    name: str,
    factory: Callable[[], Any],
    X: pd.DataFrame,
    y: pd.Series,
) -> CVResult:
    """5-fold CV for a regressor. A fresh estimator per fold, never a refit one."""
    splitter = KFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_SEED)
    folds: list[dict[str, float]] = []
    for train_idx, test_idx in splitter.split(X):
        model = factory()
        model.fit(X.iloc[train_idx], y.iloc[train_idx])
        folds.append(
            _regression_scores(y.iloc[test_idx].to_numpy(), model.predict(X.iloc[test_idx]))
        )
    return _aggregate(name, folds)


def classification_cv(
    name: str,
    factory: Callable[[], Any],
    X: pd.DataFrame,
    y: pd.Series,
) -> CVResult:
    """Stratified 5-fold CV for a classifier."""
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_SEED)
    folds: list[dict[str, float]] = []
    for train_idx, test_idx in splitter.split(X, y):
        model = factory()
        model.fit(X.iloc[train_idx], y.iloc[train_idx])
        folds.append(
            _classification_scores(y.iloc[test_idx].to_numpy(), model.predict(X.iloc[test_idx]))
        )
    return _aggregate(name, folds)


# --- Naive baselines --------------------------------------------------------


def budget_group_mean_baseline(budget: pd.Series, y: pd.Series) -> CVResult:
    """Predict the mean target of campaigns sharing this exact budget.

    `ad_budget` takes only 16 distinct values, so a group mean over it is both
    trivially simple and genuinely strong. This is the number gradient boosting
    has to beat to justify itself.
    """
    splitter = KFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_SEED)
    folds: list[dict[str, float]] = []
    for train_idx, test_idx in splitter.split(budget):
        train_means = y.iloc[train_idx].groupby(budget.iloc[train_idx]).mean()
        # A budget level unseen in training falls back to the global mean.
        predicted = budget.iloc[test_idx].map(train_means).fillna(y.iloc[train_idx].mean())
        folds.append(_regression_scores(y.iloc[test_idx].to_numpy(), predicted.to_numpy()))
    return _aggregate("baseline_budget_group_mean", folds)


def majority_class_baseline(y: pd.Series) -> CVResult:
    """Always predict the training majority class.

    Its recall on the positive class is 0, which is exactly why accuracy alone is
    a misleading headline for these targets.
    """
    splitter = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_SEED)
    folds: list[dict[str, float]] = []
    for train_idx, test_idx in splitter.split(y.to_frame(), y):
        majority = y.iloc[train_idx].mode().iloc[0]
        predicted = np.full(len(test_idx), majority)
        folds.append(_classification_scores(y.iloc[test_idx].to_numpy(), predicted))
    return _aggregate("baseline_majority_class", folds)


def improvement(model: CVResult, baseline: CVResult, metric: str) -> float:
    """Model minus baseline on one metric. The number that actually matters."""
    return round(model.metrics[metric] - baseline.metrics[metric], 6)
