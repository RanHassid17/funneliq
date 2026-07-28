"""Supabase data access.

Reads campaigns from Postgres at request time -- this is the brief's
"application must read from Supabase at runtime" requirement, not a cached copy
baked into the image.

Uses PostgREST over HTTP rather than the `supabase` client, because the client
pulls in async machinery and connection state this service does not need for
three read paths. One dependency less to reason about.

The service-role key is attached here and only here. It bypasses Row Level
Security, which is correct for a trusted server and must never reach a browser.
Callers reach these functions only after `current_user` has verified a session.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import get_settings

REQUEST_TIMEOUT = 15.0

#: Supabase is in ap-northeast-1 while Railway is US-based, so every query
#: crosses the Pacific. Selecting only needed columns keeps that round trip small.
CAMPAIGN_COLUMNS = (
    "campaign_id,ad_budget,num_leads,leads_answered,leads_not_answered,"
    "followup_1,followup_2,followup_3,followup_4,followup_5,"
    "not_closed,closed,calls_to_closed,calls_to_not_closed,"
    "customer_acquisition_cost,ltv_months,purchased,upsell,cumulative_profit,"
    "referred,data_quality_flags"
)


class SupabaseError(RuntimeError):
    """Supabase returned an error or was unreachable."""


def _headers() -> dict[str, str]:
    key = get_settings().supabase_service_role_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def _get(path: str, params: dict[str, Any]) -> Any:
    url = f"{get_settings().rest_url}/{path}"
    try:
        response = httpx.get(url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT)
    except httpx.HTTPError as exc:
        raise SupabaseError(f"Could not reach Supabase: {exc}") from exc

    if response.status_code >= 400:
        # Surface Supabase's own message: a 42501 here means RLS or grants are
        # misconfigured, which is worth reading rather than flattening to "500".
        raise SupabaseError(f"Supabase returned {response.status_code}: {response.text[:300]}")
    return response.json()


def list_campaigns(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """A page of campaigns, newest campaign_id first."""
    return _get(
        "campaigns",
        {
            "select": CAMPAIGN_COLUMNS,
            "limit": limit,
            "offset": offset,
            "order": "campaign_id.asc",
        },
    )


def get_campaign(campaign_id: str) -> dict[str, Any] | None:
    """One campaign, or None if it does not exist."""
    rows = _get(
        "campaigns",
        {"select": CAMPAIGN_COLUMNS, "campaign_id": f"eq.{campaign_id}", "limit": 1},
    )
    return rows[0] if rows else None


def count_campaigns() -> int:
    """Total rows, used by the readiness probe to prove the table is reachable."""
    url = f"{get_settings().rest_url}/campaigns"
    try:
        response = httpx.get(
            url,
            headers={**_headers(), "Prefer": "count=exact"},
            params={"select": "campaign_id", "limit": 1},
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise SupabaseError(f"Could not reach Supabase: {exc}") from exc

    if response.status_code >= 400:
        raise SupabaseError(f"Supabase returned {response.status_code}")

    # PostgREST reports the count in Content-Range as "0-0/3490".
    content_range = response.headers.get("content-range", "")
    if "/" in content_range:
        total = content_range.split("/")[-1]
        if total.isdigit():
            return int(total)
    raise SupabaseError("Supabase did not return a row count")
