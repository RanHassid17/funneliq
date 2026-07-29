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
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..crew import unavailable_reason as analyst_unavailable_reason
from .config import ConfigError, get_settings, settings_available
from .db import SupabaseError, count_campaigns
from .predictors import ModelUnavailable, model_summary
from .routes import ask, campaigns, predictions

# Recorded at import so /health can report process uptime. A restart resets it,
# which is the evidence that verifies restart-survival on the deployed service.
_STARTED_AT = time.monotonic()

#: Resolved from the package so the app runs from any working directory.
STATIC_DIR = Path(__file__).resolve().parents[3] / "static"

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
app.include_router(ask.router)


@app.get("/api/config", tags=["ops"])
def public_config() -> dict[str, str]:
    """Public Supabase configuration for the browser.

    Serves the project URL and the ANON key -- both public by design. The anon
    key is what the login screen authenticates with, and Row Level Security is
    what actually protects the data.

    Delivered from the environment at runtime rather than baked into the HTML,
    so no key is ever committed to the repository. The service-role key is not
    exposed here and must never be.
    """
    try:
        settings = get_settings()
    except ConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase is not configured on this server.",
        ) from exc
    return {
        "supabaseUrl": settings.supabase_url,
        "supabaseAnonKey": settings.supabase_anon_key,
    }


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

    # Reported but deliberately NOT part of `ready`. The analyst is optional: a
    # deployment without an LLM key serves every prediction, chart and campaign
    # comparison, and marking it unready would take a working service offline.
    analyst_blocked = analyst_unavailable_reason()

    return {
        "ready": configured and database["reachable"] and models["loaded"],
        "configured": configured,
        "database": database,
        "models": models,
        "analyst": {"available": analyst_blocked is None, "reason": analyst_blocked},
    }


# Mounted last: FastAPI matches routes in order, so the API and probes above win
# and only unmatched paths fall through to the dashboard files.
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def login_page() -> FileResponse:
        """The login screen. An unauthenticated visitor sees only this."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/dashboard.html", include_in_schema=False)
    def dashboard_page() -> FileResponse:
        """The dashboard shell.

        Serving it does not leak data: every panel fetches through the API, which
        requires a verified session, and app.js redirects to the login screen
        before rendering if there is no session.
        """
        return FileResponse(STATIC_DIR / "dashboard.html")
