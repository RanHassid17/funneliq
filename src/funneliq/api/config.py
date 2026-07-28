"""Runtime configuration, read from the environment.

No secret has a default. A missing key must fail loudly at the point of use
rather than silently falling back to something that half-works -- a service that
starts with an empty JWT secret would accept unsigned tokens, which is worse than
not starting at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


class ConfigError(RuntimeError):
    """A required environment variable is missing."""


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_role_key: str
    #: Only needed by projects still signing tokens symmetrically. Projects on
    #: asymmetric signing keys verify via JWKS and never use this.
    supabase_jwt_secret: str
    #: PUBLIC. Safe in the browser -- it is what the login screen authenticates
    #: with, and Row Level Security is what actually protects the data.
    supabase_anon_key: str

    @property
    def rest_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/rest/v1"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env locally, or set it as a "
            "Railway service variable in production."
        )
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached so a request does not re-read the environment on every call.

    The SERVICE-ROLE key lives here and must never be sent to a browser. It
    bypasses Row Level Security by design, which is correct for a server holding
    it and catastrophic for a client.
    """
    return Settings(
        supabase_url=_required("SUPABASE_URL"),
        supabase_service_role_key=_required("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_jwt_secret=os.environ.get("SUPABASE_JWT_SECRET", "").strip(),
        supabase_anon_key=_required("SUPABASE_ANON_KEY"),
    )


def settings_available() -> bool:
    """Whether the service is configured, without raising.

    Used by the readiness probe so it can report a clear "not configured" state
    instead of returning a 500 stack trace.
    """
    try:
        get_settings()
    except ConfigError:
        return False
    return True
