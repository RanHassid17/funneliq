"""ES256 verification through JWKS — the path real Supabase sessions use.

This file exists because of a production bug. `auth.py` originally verified
HS256 only, which passed every test (they minted HS256 tokens) and then rejected
every genuine session token, because the Supabase project signs users with
asymmetric ES256 keys published at a JWKS endpoint.

The lesson is in the shape of the old tests: they asserted the verifier accepted
what the *tests* produced, not what *Supabase* produces. Here the tokens are
signed with a real EC private key and verified against the matching public key
served through a stubbed JWKS endpoint, so the code path under test is the one
that runs in production.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from funneliq.api import auth
from funneliq.api.config import get_settings

KEY_ID = "test-signing-key"


@pytest.fixture(scope="module")
def keypair() -> tuple[Any, dict[str, Any]]:
    """An EC P-256 keypair plus its JWKS representation, as Supabase publishes."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": KEY_ID, "use": "sig", "alg": "ES256"})
    return private_key, {"keys": [jwk]}


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch, keypair) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    # Deliberately absent: an asymmetric project has no symmetric secret, and the
    # API must work without one.
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    auth._jwk_client.cache_clear()

    _, jwks = keypair

    class StubJWKClient:
        """Serves the public key without a network call to Supabase."""

        def __init__(self, *_: Any, **__: Any) -> None:
            self._keyset = jwt.PyJWKSet.from_dict(jwks)

        def get_signing_key_from_jwt(self, token: str) -> Any:
            kid = jwt.get_unverified_header(token)["kid"]
            for key in self._keyset.keys:
                if key.key_id == kid:
                    return key
            raise jwt.PyJWKClientError(f"Unknown key id {kid}")

    monkeypatch.setattr(auth, "PyJWKClient", StubJWKClient)
    yield
    get_settings.cache_clear()
    auth._jwk_client.cache_clear()


@pytest.fixture
def client() -> TestClient:
    from funneliq.api.main import app

    return TestClient(app)


def es256_token(private_key: Any, **overrides: Any) -> str:
    claims: dict[str, Any] = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "email": "analyst@northbound.example",
        "role": "authenticated",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": KEY_ID})


def test_real_shaped_es256_token_is_accepted(client: TestClient, keypair) -> None:
    """The regression: this is what a genuine Supabase session token looks like."""
    private_key, _ = keypair

    response = client.get(
        "/api/models", headers={"Authorization": f"Bearer {es256_token(private_key)}"}
    )

    assert response.status_code == 200


def test_asymmetric_project_needs_no_jwt_secret(client: TestClient, keypair) -> None:
    """SUPABASE_JWT_SECRET is unset in this module's fixture, by design."""
    private_key, _ = keypair

    assert get_settings().supabase_jwt_secret == ""
    assert (
        client.get(
            "/api/models", headers={"Authorization": f"Bearer {es256_token(private_key)}"}
        ).status_code
        == 200
    )


def test_es256_token_signed_by_a_different_key_is_refused(client: TestClient) -> None:
    """A valid-looking ES256 token from the wrong issuer must not be trusted."""
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    forged = jwt.encode(
        {"sub": "attacker", "aud": "authenticated", "exp": int(time.time()) + 60},
        attacker_key,
        algorithm="ES256",
        headers={"kid": KEY_ID},
    )

    response = client.get("/api/models", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


def test_expired_es256_token_is_refused(client: TestClient, keypair) -> None:
    private_key, _ = keypair
    expired = es256_token(private_key, exp=int(time.time()) - 60)

    response = client.get("/api/models", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_wrong_audience_es256_token_is_refused(client: TestClient, keypair) -> None:
    private_key, _ = keypair
    other = es256_token(private_key, aud="another-service")

    response = client.get("/api/models", headers={"Authorization": f"Bearer {other}"})

    assert response.status_code == 401


def test_unsigned_token_is_refused(client: TestClient) -> None:
    """`alg: none` must never be a verification path."""
    unsigned = jwt.encode({"sub": "x", "aud": "authenticated"}, key="", algorithm="none")

    response = client.get("/api/models", headers={"Authorization": f"Bearer {unsigned}"})

    assert response.status_code == 401


def test_hs256_token_refused_when_no_secret_is_configured(client: TestClient) -> None:
    """Without a symmetric secret there is nothing to verify a symmetric token against."""
    symmetric = jwt.encode(
        {"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 60},
        "some-secret",
        algorithm="HS256",
    )

    response = client.get("/api/models", headers={"Authorization": f"Bearer {symmetric}"})

    assert response.status_code == 401
