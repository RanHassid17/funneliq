"""The extrapolation guard, and the Phase 7 defect that motivated it.

`POST /api/predict/ltv` with a zero-lead campaign used to return **33.66
months** and a **35.6%** upsell probability, bare, with nothing marking either
as unsupported. No campaign in the 3,490 training rows has fewer than 11 leads,
and the 173 campaigns that closed nothing average 4.7 months with an upsell rate
of exactly 0.0. The number was not merely uncertain; it was an answer to a
question the model had never been asked.

These tests fix the behaviour in place: the prediction is still returned,
because a campaign that spent its budget and reached no one is a real thing, but
it is returned labelled.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from funneliq.api.config import get_settings
from funneliq.api.distribution import observed_ranges, out_of_range
from test_auth import TEST_SECRET, make_token


@pytest.fixture(autouse=True)
def configured_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    from funneliq.api.main import app

    return TestClient(app)


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


ZERO_LEAD_CAMPAIGN = {
    "ad_budget": 3000,
    "num_leads": 0,
    "leads_answered": 0,
    "followup_1": 0,
    "followup_2": 0,
}


# --- The regression ---------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/predict/ltv",
        "/api/predict/upsell",
        "/api/predict/referral-score",
        "/api/predict/profit",
    ],
)
def test_zero_lead_campaign_is_never_answered_bare(
    client: TestClient, auth: dict[str, str], path: str
) -> None:
    """The Phase 7 defect. Every predictor must label this, not just LTV."""
    body = client.post(path, json=ZERO_LEAD_CAMPAIGN, headers=auth).json()

    assert body["in_distribution"] is False
    assert "EXTRAPOLATION" in body["warning"]


def test_the_warning_names_the_offending_field_and_the_observed_range(
    client: TestClient, auth: dict[str, str]
) -> None:
    """ "Out of range" is not actionable. "num_leads=0, observed 11-139" is."""
    body = client.post("/api/predict/ltv", json=ZERO_LEAD_CAMPAIGN, headers=auth).json()

    flagged = {f["field"] for f in body["out_of_range"]}
    assert "num_leads" in flagged
    assert "num_leads=0" in body["warning"]
    assert "11" in body["warning"]


def test_a_zero_funnel_says_the_outcome_has_no_meaningful_value(
    client: TestClient, auth: dict[str, str]
) -> None:
    """A campaign that reached nobody produced no customers to have a lifetime."""
    body = client.post("/api/predict/ltv", json=ZERO_LEAD_CAMPAIGN, headers=auth).json()

    assert "no customers" in body["warning"]


def test_the_prediction_is_still_returned(client: TestClient, auth: dict[str, str]) -> None:
    """Flagged, not refused. A campaign that spent budget and got nothing is real."""
    body = client.post("/api/predict/ltv", json=ZERO_LEAD_CAMPAIGN, headers=auth).json()

    assert "predicted_ltv_months" in body


# --- Not crying wolf --------------------------------------------------------


def test_an_ordinary_campaign_is_not_flagged(client: TestClient, auth: dict[str, str]) -> None:
    body = client.post(
        "/api/predict/upsell",
        json={
            "ad_budget": 3000,
            "num_leads": 40,
            "leads_answered": 26,
            "followup_1": 20,
            "followup_2": 15,
        },
        headers=auth,
    ).json()

    assert body["in_distribution"] is True
    assert "warning" not in body


def test_a_budget_only_request_checks_only_the_budget(
    client: TestClient, auth: dict[str, str]
) -> None:
    """The subtlety that makes this usable.

    Every funnel count defaults to zero and zero is outside all their observed
    ranges. Checking defaults would flag `{"ad_budget": 3000}` -- an ordinary
    pre-launch request that reads no funnel field at all -- as extrapolation, and
    a warning that fires on the normal path is a warning people learn to ignore.
    """
    body = client.post("/api/predict/ltv", json={"ad_budget": 3000}, headers=auth).json()

    assert body["in_distribution"] is True


def test_an_out_of_range_budget_is_flagged(client: TestClient, auth: dict[str, str]) -> None:
    """₪50,000 as one campaign is 2.5x the observed maximum — the brief's own trap."""
    body = client.post("/api/predict/profit", json={"ad_budget": 50_000}, headers=auth).json()

    assert body["in_distribution"] is False
    assert any(f["field"] == "ad_budget" for f in body["out_of_range"])


# --- The ranges themselves --------------------------------------------------


def test_ranges_come_from_the_training_data_not_a_constant() -> None:
    """Hard-coded bounds drift away from the data the moment it is reloaded."""
    ranges = observed_ranges()

    assert ranges["num_leads"][0] >= 1, "no campaign in the data has zero leads"
    assert ranges["ad_budget"] == (500.0, 20000.0)


def test_unknown_fields_are_ignored_rather_than_flagged() -> None:
    assert out_of_range({"not_a_campaign_field": 999}) == []


# --- The agent path ---------------------------------------------------------


def test_the_crew_tool_carries_the_same_warning() -> None:
    """An agent must not be able to reach an unflagged number the API labels.

    Without this the analyst could quote 33.66 months to a user as a plain fact
    while the dashboard showed the same figure marked unsupported.
    """
    import json

    from funneliq.crew.tools import run_model

    result = json.loads(run_model("ltv_months", ad_budget=3000, num_leads=0, leads_answered=0))

    assert result["in_distribution"] is False
    assert "EXTRAPOLATION" in result["warning"]


# --- Stale assets -----------------------------------------------------------


@pytest.mark.parametrize("path", ["/static/app.js", "/static/styles.css", "/dashboard.html", "/"])
def test_dashboard_assets_are_revalidated_rather_than_cached_blind(
    client: TestClient, path: str
) -> None:
    """Phase 7: the deploy was right and the user still saw the old page.

    Starlette's StaticFiles sends `last-modified` and an `etag` but no
    `cache-control`, so browsers apply a heuristic freshness lifetime and reuse
    the file without asking. Phase 6's "Ask the analyst" panel shipped, deployed
    and reported available, and remained invisible until a hard reload.

    `no-cache` means "revalidate before use", not "never cache": an unchanged
    file still costs a 304 with no body.
    """
    response = client.get(path)

    assert response.status_code == 200
    assert "no-cache" in response.headers.get("cache-control", "")
