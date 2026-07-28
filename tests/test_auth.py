"""Authentication boundary.

The brief's central security requirement is that FunnelIQ sits behind a login.
These tests assert that from the outside: no token, a forged token, an expired
token and a wrong-audience token must all be refused, and only a correctly
signed one admitted.

Tokens here are minted locally with a test secret. No real credential is
involved, and none is needed -- the point is that the API verifies a signature
rather than trusting the caller.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import jwt
import pytest
from fastapi.testclient import TestClient

from funneliq.api.config import get_settings

TEST_SECRET = "test-jwt-secret-not-a-real-credential"
PROTECTED_ROUTES = [
    ("GET", "/api/campaigns"),
    ("GET", "/api/campaigns/compare?a=CMP-00000&b=CMP-00001"),
    ("GET", "/api/campaigns/CMP-00000"),
    ("GET", "/api/models"),
    ("GET", "/api/funnel/dropout"),
    ("POST", "/api/predict/ltv"),
    ("POST", "/api/predict/upsell"),
    ("POST", "/api/predict/referral-score"),
    ("POST", "/api/predict/profit"),
    ("POST", "/api/budget/simulate"),
]


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


def make_token(**overrides: object) -> str:
    claims: dict[str, object] = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "email": "analyst@northbound.example",
        "role": "authenticated",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, TEST_SECRET, algorithm="HS256")


# --- The gate ---------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES)
def test_every_data_route_refuses_an_anonymous_caller(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, json={"ad_budget": 3000})

    assert response.status_code == 401, f"{method} {path} was reachable without a token"


def test_forged_token_is_refused(client: TestClient) -> None:
    """Signed with the wrong secret: the signature check must catch it."""
    forged = jwt.encode({"sub": "attacker", "aud": "authenticated"}, "wrong-secret", "HS256")

    response = client.get("/api/models", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


def test_expired_token_is_refused(client: TestClient) -> None:
    expired = make_token(exp=int(time.time()) - 60)

    response = client.get("/api/models", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_wrong_audience_is_refused(client: TestClient) -> None:
    """A token for another audience is not a session for this API."""
    other = make_token(aud="some-other-service")

    response = client.get("/api/models", headers={"Authorization": f"Bearer {other}"})

    assert response.status_code == 401


def test_malformed_token_is_refused(client: TestClient) -> None:
    response = client.get("/api/models", headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401


def test_token_without_subject_is_refused(client: TestClient) -> None:
    """No subject means no user, even with a valid signature."""
    anonymous = jwt.encode({"aud": "authenticated"}, TEST_SECRET, algorithm="HS256")

    response = client.get("/api/models", headers={"Authorization": f"Bearer {anonymous}"})

    assert response.status_code == 401


def test_valid_token_is_admitted(client: TestClient) -> None:
    response = client.get("/api/models", headers={"Authorization": f"Bearer {make_token()}"})

    assert response.status_code == 200
    assert "models" in response.json()


def test_error_message_does_not_leak_why_verification_failed(client: TestClient) -> None:
    """Telling a caller how their forgery failed helps them forge a better one."""
    forged = jwt.encode({"sub": "x", "aud": "authenticated"}, "wrong-secret", "HS256")

    detail = client.get("/api/models", headers={"Authorization": f"Bearer {forged}"}).json()[
        "detail"
    ]

    assert "signature" not in detail.lower()
    assert "secret" not in detail.lower()


# --- The public config endpoint ---------------------------------------------


def test_public_config_serves_the_anon_key(client: TestClient) -> None:
    """The browser needs the project URL and anon key to run the login screen."""
    body = client.get("/api/config").json()

    assert body["supabaseUrl"] == "https://example.supabase.co"
    assert body["supabaseAnonKey"] == "test-anon-key"


def test_public_config_never_exposes_the_service_role_key(client: TestClient) -> None:
    """The single most damaging mistake this project could make.

    The service-role key bypasses Row Level Security. If it ever reached the
    browser, every campaign row would be readable by anyone who opened devtools,
    and RLS would be decoration.
    """
    raw = client.get("/api/config").text

    assert "test-service-role-key" not in raw
    assert "service" not in raw.lower().replace("supabaseurl", "")


def test_static_pages_are_public_but_carry_no_data(client: TestClient) -> None:
    """Serving the dashboard shell is safe; its data still needs a session.

    The page is static HTML. Every number on it arrives through the API, which
    requires a verified token, and the client redirects to the login screen
    before rendering if there is no session.
    """
    page = client.get("/dashboard.html")

    assert page.status_code == 200
    assert "campaign" in page.text.lower()
    assert "eyJ" not in page.text, "no JWT may be baked into the page"


# --- Public routes ----------------------------------------------------------


def test_health_needs_no_token(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_needs_no_token(client: TestClient) -> None:
    """The platform probes readiness without credentials."""
    assert client.get("/ready").status_code == 200
