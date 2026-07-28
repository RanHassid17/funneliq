"""Estimator factories for the three required gradient-boosting libraries.

Factories rather than instances, because cross-validation needs a fresh model per
fold -- reusing one silently carries state across folds and inflates scores.

Defaults are deliberately modest. The comparison the brief asks for is between
libraries on equal terms, not a hunt for the best tuned model, and heavily tuned
defaults would confound the two.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from xgboost import XGBClassifier, XGBRegressor

from . import RANDOM_SEED

Factory = Callable[[], Any]


def regressors() -> dict[str, Factory]:
    return {
        "xgboost": lambda: XGBRegressor(
            n_estimators=300, learning_rate=0.05, max_depth=5, random_state=RANDOM_SEED
        ),
        "lightgbm": lambda: LGBMRegressor(
            n_estimators=300, learning_rate=0.05, max_depth=5, random_state=RANDOM_SEED, verbose=-1
        ),
        "catboost": lambda: CatBoostRegressor(
            iterations=300, learning_rate=0.05, depth=5, random_seed=RANDOM_SEED, verbose=0
        ),
    }


def classifiers(y: pd.Series) -> dict[str, Factory]:
    """Classifier factories with class-imbalance handling wired in.

    Each library spells the same idea differently: XGBoost wants an explicit
    positive-class weight, LightGBM and CatBoost accept a "balanced" mode.

    Worth stating honestly: both targets here sit near 40/60, which is *mild*
    imbalance. The brief requires imbalance handling and it is implemented, but
    it is not the dominant lever on these results and the write-up says so rather
    than overclaiming.
    """
    positives = int((y == 1).sum())
    negatives = int((y == 0).sum())
    scale_pos_weight = negatives / positives if positives else 1.0

    return {
        "xgboost": lambda: XGBClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=5,
            random_state=RANDOM_SEED,
            scale_pos_weight=scale_pos_weight,
        ),
        "lightgbm": lambda: LGBMClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=5,
            random_state=RANDOM_SEED,
            class_weight="balanced",
            verbose=-1,
        ),
        "catboost": lambda: CatBoostClassifier(
            iterations=300,
            learning_rate=0.05,
            depth=5,
            random_seed=RANDOM_SEED,
            auto_class_weights="Balanced",
            verbose=0,
        ),
    }


def feature_importances(model: Any, columns: list[str]) -> dict[str, float]:
    """Normalised importances, comparable across the three libraries.

    Raw importance scales differ per library (gain, split count, prediction-value
    change), so absolute values are not comparable. Normalising to sum 1 makes the
    *ranking and relative weight* comparable, which is what the brief asks for.
    """
    raw = getattr(model, "feature_importances_", None)
    if raw is None:  # pragma: no cover - all three libraries expose this
        return {}
    total = float(sum(raw)) or 1.0
    return {c: round(float(v) / total, 6) for c, v in zip(columns, raw, strict=True)}
