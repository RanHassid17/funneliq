"""Prediction, funnel and budget endpoints.

Every route requires a verified session, and every response says which model
answered and at which prediction checkpoint. A number without that context is
not actionable -- a caller needs to know whether it came from a model that beat
its baseline or one that merely tied it.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ...data.frames import load_campaign_frame
from ...models import REPORTS_DIR
from ...models.budget import recommend, simulate
from ..auth import User, current_user
from ..predictors import (
    ModelUnavailable,
    model_summary,
    predict_ltv,
    predict_profit,
    predict_referral_score,
    predict_upsell,
)
from ..schemas import BudgetSimulationInput, CampaignInput

router = APIRouter(prefix="/api", tags=["predictions"])


def _model_missing(exc: ModelUnavailable) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


def _predict(fn: Any, campaign: CampaignInput) -> dict[str, Any]:
    try:
        return fn(campaign.to_features())
    except ModelUnavailable as exc:
        raise _model_missing(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/predict/ltv")
def ltv(campaign: CampaignInput, _: User = Depends(current_user)) -> dict[str, Any]:
    """Package 2. Served by the budget baseline, which boosting could not beat."""
    return _predict(predict_ltv, campaign)


@router.post("/predict/upsell")
def upsell(campaign: CampaignInput, _: User = Depends(current_user)) -> dict[str, Any]:
    """Package 3. Served by CatBoost, which beat its baseline decisively."""
    return _predict(predict_upsell, campaign)


@router.post("/predict/referral-score")
def referral_score(campaign: CampaignInput, _: User = Depends(current_user)) -> dict[str, Any]:
    """Package 4. A 0-100 CAMPAIGN referral likelihood, never an individual's."""
    return _predict(predict_referral_score, campaign)


@router.post("/predict/profit")
def profit(campaign: CampaignInput, _: User = Depends(current_user)) -> dict[str, Any]:
    """Package 6. Pre-launch, so it reads only `ad_budget`."""
    return _predict(predict_profit, campaign)


@router.get("/models")
def models(_: User = Depends(current_user)) -> dict[str, Any]:
    """What is being served, with each model's score against its baseline."""
    return {"models": model_summary()}


@router.post("/budget/simulate")
def budget_simulate(
    request: BudgetSimulationInput, _: User = Depends(current_user)
) -> dict[str, Any]:
    """Package 6. Allocation strategies for a monthly budget.

    Scenarios whose per-campaign budget falls outside the observed training range
    are flagged and excluded from the recommendation. Tree models answer
    out-of-range questions with the nearest leaf value at full apparent
    confidence, and presenting that as a forecast would be fabrication.
    """
    try:
        scenarios = simulate(
            load_campaign_frame(),
            monthly_budget=request.monthly_budget,
            splits=tuple(request.splits),
        )
    except ModelUnavailable as exc:
        raise _model_missing(exc) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profit model unavailable. Run: python -m funneliq.models.train",
        ) from exc

    if not any(s.in_distribution for s in scenarios):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Every requested split falls outside the observed budget range, so none can "
                "be predicted. Try more campaigns, or a smaller monthly budget."
            ),
        )
    return recommend(scenarios)


@router.get("/funnel/dropout")
def funnel_dropout(_: User = Depends(current_user)) -> dict[str, Any]:
    """Package 5. Stage-by-stage follow-up dropout, with the recommendation.

    Served from the committed profile rather than recomputed per request: it is a
    property of the whole dataset, identical for every caller.
    """
    profile_path = REPORTS_DIR / "profile.json"
    if not profile_path.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Funnel profile unavailable. Run: python -m funneliq.data.profile",
        )

    stages = json.loads(profile_path.read_text())["followup_dropout"]
    worst = max(stages, key=lambda s: s["dropout_from_previous"])
    best = min(stages, key=lambda s: s["dropout_from_previous"])

    return {
        "stages": stages,
        "largest_dropout_stage": worst["stage"],
        "most_retentive_stage": best["stage"],
        "recommendation": (
            f"Dropout is lowest at {best['stage']} "
            f"({best['dropout_from_previous']:.1%}) and highest at {worst['stage']} "
            f"({worst['dropout_from_previous']:.1%}). Cutting contact after the third "
            "follow-up would abandon leads at their most engaged stage; the genuine "
            "cliff is later."
        ),
    }
