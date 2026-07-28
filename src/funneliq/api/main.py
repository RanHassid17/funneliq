"""FunnelIQ API — application entrypoint.

Phase 0 deliberately ships only a health check. The brief's advice is to get the
boring skeleton deployed first, because deployment and auth failures are far
easier to read when there is almost no code to blame. Everything else grows
inside a pipeline that already works.
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI

# Recorded at import time so /health can report how long this process has been
# alive. A restart resets it, which is exactly what makes it useful evidence
# when verifying that the Railway deployment survives a restart.
_STARTED_AT = time.monotonic()

app = FastAPI(
    title="FunnelIQ",
    version="0.1.0",
    summary="Campaign-intelligence API for Northbound Media.",
)


def _commit_sha() -> str:
    """Return the deployed commit, or "unknown" when running outside Railway.

    Railway injects RAILWAY_GIT_COMMIT_SHA at build time. Reporting it from
    /health is what lets us prove *which* revision is actually serving traffic
    rather than inferring it from a green deploy log.
    """
    return os.getenv("RAILWAY_GIT_COMMIT_SHA", "unknown")


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness check. Public by design — everything else requires a session.

    This intentionally does not touch Supabase. A health check that fails when
    the database is briefly unreachable causes the platform to restart a process
    that was never broken. Database reachability gets its own readiness check in
    Phase 4, once there is a database to check.
    """
    return {
        "status": "ok",
        "service": "funneliq",
        "version": app.version,
        "commit": _commit_sha(),
        "uptime_seconds": round(time.monotonic() - _STARTED_AT, 1),
    }
