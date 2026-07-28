"""Shared test fixtures.

`make_row` returns a campaign that satisfies every invariant, so a test can break
exactly one thing and attribute the failure to it.
"""

from __future__ import annotations


def make_row(**overrides: object) -> dict[str, object]:
    """A structurally valid campaign, for tests to selectively break.

    Every derived quantity is internally consistent: 32 + 16 == 48 leads,
    follow-ups are non-increasing, 5 + 4 == 9 == followup_5, and the CAC of 800
    is exactly floor(4000 / 5).
    """
    row: dict[str, object] = {
        "ad_budget": 4000,
        "num_leads": 48,
        "leads_answered": 32,
        "leads_not_answered": 16,
        "followup_1": 25,
        "followup_2": 18,
        "followup_3": 15,
        "followup_4": 13,
        "followup_5": 9,
        "not_closed": 4,
        "closed": 5,
        "calls_to_closed": 3,
        "calls_to_not_closed": 3,
        "customer_acquisition_cost": 800,
        "ltv_months": 28.0,
        "purchased": 1,
        "upsell": 0,
        "cumulative_profit": 15048.0,
        "referred": "Yes",
    }
    row.update(overrides)
    return row
