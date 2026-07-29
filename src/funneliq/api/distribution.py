"""Is this campaign one the models have actually seen?

Phase 7 found the gap this closes. `POST /api/predict/ltv` with a zero-lead
campaign returned **33.66 months** and a **35.6%** upsell probability, at full
apparent confidence. Both numbers are indefensible:

- No campaign in the 3,490 training rows has fewer than **11 leads**, 4 answered,
  or 3 reaching follow-up 1. A zero-lead campaign is not a hard case, it is a
  case the models have never seen.
- A campaign that generated no leads produced no customers, so "the average
  lifetime of the customers this campaign produced" does not have a value. The
  173 campaigns that closed nothing average **4.7 months**, not 33.7, and their
  upsell rate is exactly **0.0**.

The 33.66 arrives because LTV is served by the budget group-mean baseline, which
reads only `ad_budget` and is therefore structurally blind to a funnel that
produced nobody. That is not a bug in the baseline; it is a question the baseline
was never entitled to answer.

`budget.py` already had this idea for `ad_budget` alone -- scenarios outside the
observed range are labelled and excluded from the recommendation. This module
generalises it to every input a caller can supply, and deliberately reuses the
same word, `in_distribution`, so the dashboard and the API mean one thing by it.

**Flagged, not refused.** A campaign that spent its budget and got no leads is a
real thing that happens, and answering "that is not a valid request" would be
wrong. What the caller needs is the number *and* the fact that it is
extrapolation.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..data.frames import load_campaign_frame

#: Inputs a caller can supply that any served model reads, directly or through a
#: derived metric. `ad_budget` is here as well as in `budget.py` because a
#: prediction request and a budget scenario are checked on different paths.
CHECKED_FIELDS = (
    "ad_budget",
    "num_leads",
    "leads_answered",
    "followup_1",
    "followup_2",
)


@lru_cache(maxsize=1)
def observed_ranges() -> dict[str, tuple[float, float]]:
    """Min and max of each checked field across the training data.

    Computed from the same frame the models were trained on rather than
    hard-coded, so the guard cannot drift away from the data if the dataset is
    reloaded. Cached because it is identical for every request.
    """
    frame = load_campaign_frame()
    return {
        field: (float(frame[field].min()), float(frame[field].max()))
        for field in CHECKED_FIELDS
        if field in frame.columns
    }


def out_of_range(supplied: dict[str, float]) -> list[dict[str, Any]]:
    """Which supplied fields fall outside anything the models were trained on.

    Only fields the caller actually sent are checked. `CampaignInput` defaults
    the funnel counts to zero, and flagging a default the caller never chose
    would report extrapolation on `{"ad_budget": 3000}` -- a perfectly ordinary
    pre-launch request that reads no funnel field at all.
    """
    ranges = observed_ranges()
    findings: list[dict[str, Any]] = []
    for field, value in supplied.items():
        if field not in ranges:
            continue
        low, high = ranges[field]
        if value < low or value > high:
            findings.append(
                {
                    "field": field,
                    "value": value,
                    "observed_min": low,
                    "observed_max": high,
                }
            )
    return findings


def annotate(result: dict[str, Any], supplied: dict[str, float]) -> dict[str, Any]:
    """Attach the distribution verdict to a prediction response."""
    findings = out_of_range(supplied)
    result["in_distribution"] = not findings
    if findings:
        result["out_of_range"] = findings
        result["warning"] = _warning(findings)
    return result


def _warning(findings: list[dict[str, Any]]) -> str:
    """Say which input is unsupported and why the number cannot be trusted.

    Named per field rather than a generic "out of range", because "your budget
    is too high" and "this campaign generated no leads" call for different
    reactions from whoever is reading it.
    """
    parts = [
        f"{f['field']}={f['value']:g} (observed {f['observed_min']:g}–{f['observed_max']:g})"
        for f in findings
    ]
    degenerate = any(f["field"] != "ad_budget" and f["value"] == 0 for f in findings)
    detail = (
        " A campaign that reached no one produces no customers, so this outcome has no "
        "meaningful value for it."
        if degenerate
        else ""
    )
    return (
        "EXTRAPOLATION — this campaign is unlike anything in the training data: "
        + ", ".join(parts)
        + "."
        + detail
        + " Treat the number as unsupported rather than uncertain."
    )
