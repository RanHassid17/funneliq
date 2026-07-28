"""Supabase JWT verification.

The browser authenticates against Supabase Auth with the PUBLIC anon key and
receives a signed JWT. It sends that token to this API, which verifies the
signature server-side using the project's JWT secret.

The property this buys: the API trusts a *cryptographic signature*, not the
client's word. A caller cannot mint a session by editing a request, and the
service-role key never leaves the server.

Verification is deliberately strict -- signature, expiry, and the `authenticated`
audience are all checked. An expired token is rejected rather than tolerated,
because "the session ended" is exactly the case a login gate exists to catch.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import ConfigError, get_settings

# auto_error=False so a missing header produces our own 401 with a useful
# message, rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)

#: Supabase issues user tokens with this audience.
EXPECTED_AUDIENCE = "authenticated"


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


def verify_token(token: str) -> User:
    """Decode and validate a Supabase JWT, or raise 401."""
    try:
        secret = get_settings().supabase_jwt_secret
    except ConfigError as exc:  # pragma: no cover - misconfiguration, not a request error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server.",
        ) from exc

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=EXPECTED_AUDIENCE,
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Session expired. Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        # Covers bad signature, wrong audience, malformed token. The message is
        # deliberately vague: telling a caller *why* their forged token failed
        # helps them forge a better one.
        raise _unauthorized("Invalid authentication token.") from exc

    subject = claims.get("sub")
    if not subject:
        raise _unauthorized("Token is missing a subject claim.")

    return User(id=subject, email=claims.get("email"), role=claims.get("role"))


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """FastAPI dependency: require a valid Supabase session.

    Attach to every route that exposes campaign data or predictions. `/health`
    stays public so the platform can probe it without a token.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing bearer token. Sign in to use FunnelIQ.")
    return verify_token(credentials.credentials)
