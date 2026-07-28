"""Campaign records read live from Supabase.

This is the brief's runtime-read requirement: the data comes from Postgres on
each request, not from a copy baked into the container image.

Every route requires a verified session. There is no public campaign data.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...data.metrics import add_derived_metrics
from ..auth import User, current_user
from ..db import SupabaseError, get_campaign, list_campaigns

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

#: Derived metrics worth returning alongside a campaign. The full set is wide;
#: these are the ones a person comparing two campaigns actually reads.
COMPARISON_METRICS = [
    "answer_rate",
    "cost_per_lead",
    "close_rate_funnel",
    "close_rate_leads",
    "profit_per_lead",
    "profit_per_closed",
    "return_on_ad_spend",
    "stage_retention_1",
    "stage_retention_2",
    "stage_retention_3",
    "stage_retention_4",
    "stage_retention_5",
]


def _unavailable(exc: SupabaseError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Campaign data is temporarily unavailable: {exc}",
    )


def _with_metrics(row: dict[str, Any]) -> dict[str, Any]:
    """Attach derived metrics using the same code path as training.

    NaN becomes None so the JSON is valid -- `NaN` is not legal JSON, and a
    metric with a zero denominator is genuinely unknown rather than zero.
    """
    # Missing profit stays missing: it is not filled in here.
    enriched = add_derived_metrics(pd.DataFrame([row])).iloc[0]
    metrics = {
        name: (None if pd.isna(enriched[name]) else round(float(enriched[name]), 6))
        for name in COMPARISON_METRICS
        if name in enriched
    }
    return {**row, "metrics": metrics}


@router.get("")
def get_campaigns(
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(current_user),
) -> dict[str, Any]:
    """A page of campaigns, straight from Supabase."""
    try:
        rows = list_campaigns(limit=limit, offset=offset)
    except SupabaseError as exc:
        raise _unavailable(exc) from exc

    return {
        "campaigns": [_with_metrics(row) for row in rows],
        "limit": limit,
        "offset": offset,
        "returned": len(rows),
    }


@router.get("/compare")
def compare_campaigns(
    a: str = Query(description="First campaign_id"),
    b: str = Query(description="Second campaign_id"),
    _: User = Depends(current_user),
) -> dict[str, Any]:
    """Two campaigns side by side, with the difference on each shared metric.

    Deltas are computed server-side so the dashboard and any other client agree
    on what "better" means, rather than each recomputing it.
    """
    try:
        first, second = get_campaign(a), get_campaign(b)
    except SupabaseError as exc:
        raise _unavailable(exc) from exc

    missing = [cid for cid, row in ((a, first), (b, second)) if row is None]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown campaign_id: {', '.join(missing)}",
        )

    assert first is not None and second is not None
    left, right = _with_metrics(first), _with_metrics(second)

    deltas = {
        name: round(right["metrics"][name] - left["metrics"][name], 6)
        for name in left["metrics"]
        if left["metrics"].get(name) is not None and right["metrics"].get(name) is not None
    }

    return {"a": left, "b": right, "delta_b_minus_a": deltas}


@router.get("/{campaign_id}")
def get_one(campaign_id: str, _: User = Depends(current_user)) -> dict[str, Any]:
    try:
        row = get_campaign(campaign_id)
    except SupabaseError as exc:
        raise _unavailable(exc) from exc

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown campaign_id: {campaign_id}"
        )
    return _with_metrics(row)
