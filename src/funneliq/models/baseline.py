"""The budget group-mean estimator.

This is not scaffolding for comparison -- it is the model FunnelIQ actually
serves for campaign lifetime and campaign profit, because gradient boosting
failed to beat it on either (see docs/MODEL_CARDS.md and reports/tuning_ltv.json,
where 114 tuned configurations all lost).

Predicting the mean outcome of campaigns sharing a budget level is a legitimate
model when `ad_budget` takes 16 discrete values and drives the target. Serving it
instead of a 300-tree ensemble removes latency, dependencies and opacity at no
cost in accuracy.

Implements the scikit-learn `fit`/`predict` surface so it drops into the same
cross-validation harness and registry as the boosted models.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BUDGET_COLUMN = "ad_budget"


class BudgetGroupMeanRegressor:
    """Predict the training mean of campaigns sharing the same `ad_budget`."""

    def __init__(self, budget_column: str = BUDGET_COLUMN) -> None:
        self.budget_column = budget_column
        self.group_means_: pd.Series | None = None
        self.global_mean_: float | None = None

    @property
    def feature_importances_(self) -> np.ndarray:
        """Budget explains everything here, by construction.

        Present so the registry and reporting code can treat this like any other
        estimator rather than special-casing it.
        """
        return np.array([1.0])

    def _budget(self, X: pd.DataFrame | pd.Series) -> pd.Series:
        if isinstance(X, pd.Series):
            return X
        return X[self.budget_column]

    def fit(self, X: pd.DataFrame | pd.Series, y: pd.Series) -> BudgetGroupMeanRegressor:
        budget = self._budget(X)
        target = pd.Series(np.asarray(y, dtype="float64"), index=budget.index)
        self.group_means_ = target.groupby(budget).mean()
        # Fallback for a budget level never seen in training. Without it, an
        # unseen level would predict NaN and the failure would surface as a
        # confusing downstream error rather than a sensible default.
        self.global_mean_ = float(target.mean())
        return self

    def predict(self, X: pd.DataFrame | pd.Series) -> np.ndarray:
        if self.group_means_ is None or self.global_mean_ is None:
            raise RuntimeError("BudgetGroupMeanRegressor.predict called before fit")
        budget = self._budget(X)
        return budget.map(self.group_means_).fillna(self.global_mean_).to_numpy(dtype="float64")

    def known_budgets(self) -> list[float]:
        """Budget levels this model actually learned from.

        The budget simulator uses this to tell a supported prediction from an
        extrapolation, rather than presenting both with equal confidence.
        """
        if self.group_means_ is None:
            return []
        return [float(b) for b in self.group_means_.index]
