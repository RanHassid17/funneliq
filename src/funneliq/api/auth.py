"""Supabase JWT verification.

The browser authenticates against Supabase Auth with the PUBLIC anon key and
receives a signed JWT. It sends that token here, and the API verifies the
signature server-side. The API trusts a cryptographic signature, not the
client's word, and the service-role key never leaves the server.

**Two signing schemes exist and both are supported.** Supabase has moved to
asymmetric signing keys (ES256/RS256) published at a JWKS endpoint; older
projects sign symmetrically (HS256) with the project's shared JWT secret. The
first implementation here assumed HS256 only and rejected every real session
token on an asymmetric project, so the scheme is now selected from the token's
own header:

- `ES256` / `RS256` -> verified against the public key fetched from JWKS.
- `HS256`           -> verified against `SUPABASE_JWT_SECRET`.

That header read is safe. It selects a verification path; it never grants
trust, and a token claiming `alg: none` is refused because neither path allows
it. There is no algorithm-confusion risk either: the HS256 path uses the shared
secret, never a public key.

Verification is otherwise strict -- signature, expiry, and the `authenticated`
audience are all checked. An expired token is rejected rather than tolerated,
because "the session ended" is exactly what a login gate exists to catch.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import ConfigError, get_settings

# auto_error=False so a missing header produces our own 401 with a useful
# message, rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)

#: Supabase issues user tokens with this audience.
EXPECTED_AUDIENCE = "authenticated"

#: Asymmetric algorithms verified via the project's published JWKS.
ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256"})


@dataclass(frozen=True)
class User:
    """The authenticated caller, as asserted by a verified Supabase token."""

    id: str
    email: str | None
    role: str | None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    """Client for the project's public signing keys.

    Cached because it keeps its own key cache: fetching JWKS on every request
    would add a round trip to Supabase for each API call.
    """
    url = get_settings().supabase_url.rstrip("/")
    return PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def _decode(token: str, algorithm: str) -> dict[str, object]:
    """Verify `token` using whichever scheme its header declares."""
    if algorithm in ASYMMETRIC_ALGORITHMS:
        key = _jwk_client().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token, key, algorithms=sorted(ASYMMETRIC_ALGORITHMS), audience=EXPECTED_AUDIENCE
        )

    secret = get_settings().supabase_jwt_secret
    if not secret:
        raise jwt.InvalidTokenError("Symmetric token received but no JWT secret is configured")
    return jwt.decode(token, secret, algorithms=["HS256"], audience=EXPECTED_AUDIENCE)


def verify_token(token: str) -> User:
    """Decode and validate a Supabase JWT, or raise 401."""
    try:
        get_settings()
    except ConfigError as exc:  # pragma: no cover - misconfiguration, not a request error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server.",
        ) from exc

    try:
        algorithm = str(jwt.get_unverified_header(token).get("alg", ""))
        claims = _decode(token, algorithm)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Session expired. Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        # Covers bad signature, wrong audience, unknown algorithm, malformed
        # token. The message is deliberately vague: telling a caller *why* their
        # forged token failed helps them forge a better one.
        raise _unauthorized("Invalid authentication token.") from exc
    except Exception as exc:  # JWKS fetch failures reach us as transport errors.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach the identity provider to verify your session.",
        ) from exc

    subject = claims.get("sub")
    if not subject:
        raise _unauthorized("Token is missing a subject claim.")

    return User(
        id=str(subject),
        email=claims.get("email"),  # type: ignore[arg-type]
        role=claims.get("role"),  # type: ignore[arg-type]
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """FastAPI dependency: require a valid Supabase session.

    Attach to every route exposing campaign data or predictions. `/health` and
    `/ready` stay public so the platform can probe them without a token.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing bearer token. Sign in to use FunnelIQ.")
    return verify_token(credentials.credentials)
