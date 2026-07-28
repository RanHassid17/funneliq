"""FunnelIQ API — application entrypoint.

Two probes, deliberately different:

- `/health` is public and answers "is this process alive". It touches nothing
  external. A health check that fails on a brief database blip makes the platform
  restart a process that was never broken.
- `/ready` answers "can this instance actually serve requests", so it *does*
  check Supabase and the model artifacts.

Everything else requires a verified Supabase session. FunnelIQ is Northbound's
internal tool, not a public API.
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI

from .config import settings_available
from .db import SupabaseError, count_campaigns
from .predictors import ModelUnavailable, model_summary
from .routes import campaigns, predictions

# Recorded at import so /health can report process uptime. A restart resets it,
# which is the evidence that verifies restart-survival on the deployed service.
_STARTED_AT = time.monotonic()

app = FastAPI(
    title="FunnelIQ",
    version="0.2.0",
    summary="Campaign-intelligence API for Northbound Media.",
    description=(
        "Every prediction describes a CAMPAIGN, never an individual customer. "
        "All routes except /health and /ready require a Supabase session."
    ),
)

app.include_router(campaigns.router)
app.include_router(predictions.router)


def _commit_sha() -> str:
    """The deployed revision, so /health proves which code is serving traffic."""
    return os.getenv("RAILWAY_GIT_COMMIT_SHA", "unknown")


@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    """Liveness. Public by design; deliberately does not touch Supabase."""
    return {
        "status": "ok",
        "service": "funneliq",
        "version": app.version,
        "commit": _commit_sha(),
        "uptime_seconds": round(time.monotonic() - _STARTED_AT, 1),
    }


@app.get("/ready", tags=["ops"])
def ready() -> dict[str, Any]:
    """Readiness: configuration, database reachability, and model artifacts.

    Reports each dependency separately rather than a single boolean, because
    "the database is unreachable" and "the models were never trained" need
    completely different fixes.
    """
    configured = settings_available()

    database: dict[str, Any] = {"reachable": False}
    if configured:
        try:
            database = {"reachable": True, "campaigns": count_campaigns()}
        except SupabaseError as exc:
            database = {"reachable": False, "error": str(exc)[:200]}
    else:
        database = {"reachable": False, "error": "Supabase environment variables are not set"}

    try:
        served = model_summary()
        models = {
            "loaded": all(m.get("available") for m in served),
            "targets": [m["target"] for m in served if m.get("available")],
        }
    except ModelUnavailable as exc:  # pragma: no cover - defensive
        models = {"loaded": False, "error": str(exc)[:200]}

    return {
        "ready": configured and database["reachable"] and models["loaded"],
        "configured": configured,
        "database": database,
        "models": models,
    }
