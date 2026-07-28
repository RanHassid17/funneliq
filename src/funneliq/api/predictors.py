"""Model loading and prediction.

Which artifact serves which target is a deliberate decision, not a default:

- `ltv_months` and `cumulative_profit` are served by the **budget group-mean
  baseline**, because gradient boosting lost to it (114 tuned configurations,
  none won) and tying it on profit. Serving a 300-tree ensemble that is no more
  accurate would buy latency and opacity for nothing.
- `upsell` and `referred` are served by their boosted models, which beat their
  baselines decisively.

Models load once at import and are held in memory. They are small (~640 KB
total), so the alternative -- loading per request -- would add latency for no
benefit.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import pandas as pd

from ..data.features import MODEL_CHECKPOINTS, feature_columns
from ..data.metrics import add_derived_metrics
from ..models.registry import ModelCard, load

#: target -> artifact name. The two regressions point at their baselines.
SERVED_MODELS: dict[str, str] = {
    "ltv_months": "ltv_months_baseline",
    "cumulative_profit": "cumulative_profit_baseline",
    "upsell": "upsell",
    "referred": "referral_score",
}


class ModelUnavailable(RuntimeError):
    """A model artifact is missing. Run funneliq.models.train."""


@lru_cache(maxsize=8)
def _load(target: str) -> tuple[Any, ModelCard]:
    name = SERVED_MODELS[target]
    try:
        return load(name)
    except FileNotFoundError as exc:
        raise ModelUnavailable(
            f"Model artifact {name!r} is missing. Run: python -m funneliq.models.train"
        ) from exc


def _feature_frame(payload: dict[str, float], target: str) -> pd.DataFrame:
    """Build a one-row feature matrix for `target` from raw campaign inputs.

    Derived metrics are recomputed here with exactly the code used in training,
    so a rate can never be defined one way offline and another way at serving
    time -- a classic and hard-to-spot source of train/serve skew.
    """
    card = _load(target)[1]
    frame = add_derived_metrics(pd.DataFrame([payload]))

    missing = [c for c in card.features if c not in frame.columns]
    if missing:
        raise ValueError(f"Cannot build features {missing} from the supplied fields.")
    return frame[card.features]


def predict_ltv(payload: dict[str, float]) -> dict[str, Any]:
    """Average customer lifetime, in months, for the customers a campaign produces."""
    model, card = _load("ltv_months")
    value = float(model.predict(_feature_frame(payload, "ltv_months"))[0])
    return {
        "predicted_ltv_months": round(max(value, 0.0), 2),
        "model": card.algorithm,
        "checkpoint": card.checkpoint,
        "note": (
            "Average lifetime of the customers this CAMPAIGN produces, not one person's tenure."
        ),
    }


def predict_profit(payload: dict[str, float]) -> dict[str, Any]:
    """Expected total profit, predictable before the campaign launches."""
    model, card = _load("cumulative_profit")
    value = float(model.predict(_feature_frame(payload, "cumulative_profit"))[0])
    return {
        "predicted_cumulative_profit": round(max(value, 0.0), 2),
        "model": card.algorithm,
        "checkpoint": card.checkpoint,
    }


def _probability(model: Any, frame: pd.DataFrame) -> float:
    return float(model.predict_proba(frame)[0][1])


def predict_upsell(payload: dict[str, float]) -> dict[str, Any]:
    """Likelihood this campaign produces at least one upsell."""
    model, card = _load("upsell")
    probability = _probability(model, _feature_frame(payload, "upsell"))
    return {
        "upsell_probability": round(probability, 4),
        "likely": probability >= 0.5,
        "model": card.algorithm,
        "checkpoint": card.checkpoint,
        "note": "Campaign-level outcome. Not a prediction about any individual customer.",
    }


def predict_referral_score(payload: dict[str, float]) -> dict[str, Any]:
    """The 0-100 super-customer score from Package 4."""
    model, card = _load("referred")
    probability = _probability(model, _feature_frame(payload, "referred"))
    return {
        "referral_score": round(probability * 100, 1),
        "referral_probability": round(probability, 4),
        "model": card.algorithm,
        "checkpoint": card.checkpoint,
        "note": (
            "CAMPAIGN referral likelihood on a 0-100 scale. This is not an individual "
            "customer's probability of referring a friend."
        ),
    }


def model_summary() -> list[dict[str, Any]]:
    """What is actually being served, with each model's honest scoreline."""
    summary: list[dict[str, Any]] = []
    for target in SERVED_MODELS:
        try:
            _, card = _load(target)
        except ModelUnavailable:
            summary.append({"target": target, "available": False})
            continue
        summary.append(
            {
                "target": target,
                "available": True,
                "algorithm": card.algorithm,
                "checkpoint": str(MODEL_CHECKPOINTS[target]),
                "features": card.features,
                "metrics": card.metrics,
                "baseline_metrics": card.baseline_metrics,
                "improvement_over_baseline": card.improvement,
                "trained_on_rows": card.rows_trained,
                "git_sha": card.git_sha,
            }
        )
    return summary


def required_fields(target: str) -> list[str]:
    """Raw columns a caller must supply for this target's features."""
    return feature_columns(target)
