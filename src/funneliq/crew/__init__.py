"""CrewAI agents for FunnelIQ.

Two entry points, deliberately separated by who pays for them:

- **Offline** (`python -m funneliq.crew.run`) drafts report sections from the
  committed evidence in `reports/`. Run by a developer, on demand.
- **Runtime** (`POST /api/ask`) answers a signed-in user's question about the
  campaign data. Every call spends money, so it is rate-limited and capped.

**Nothing in this package imports `crewai` at module import time.** The API
imports these modules on startup, and CrewAI pulls in chromadb, onnxruntime and
grpc -- roughly 220 MB of native libraries. If any of that fails to load on the
deployment platform, the correct outcome is that `/api/ask` returns 503 while
the rest of FunnelIQ keeps serving predictions. An import at the top of this
file would instead take the whole service down, which is exactly the failure
mode Phase 4 already hit once with `libgomp`.

So `crewai` is imported inside the functions that need it, and
`unavailable_reason()` is the single place that decides whether the analyst can
run at all.
"""

from __future__ import annotations

import os

#: Default model for the analyst. Overridable so a cost-sensitive deployment can
#: drop to a smaller one without a code change.
DEFAULT_MODEL = os.environ.get("FUNNELIQ_LLM_MODEL", "anthropic/claude-sonnet-5")

#: Hard ceiling on agent tool-use loops. An agent that cannot answer in this many
#: steps is looping, and looping on a metered API is how a demo becomes a bill.
MAX_ITERATIONS = 6

#: Requests per minute the crew may make to the LLM.
MAX_RPM = 10


class CrewUnavailable(RuntimeError):
    """The analyst cannot run, with a reason worth showing the caller."""


def api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def unavailable_reason() -> str | None:
    """Why the analyst cannot run, or None if it can.

    Checked before any crew is built so the endpoint can answer 503 with a
    specific cause instead of raising on a missing key halfway through a task.
    """
    if not api_key():
        return (
            "The AI analyst is not configured on this server: ANTHROPIC_API_KEY is unset. "
            "Every other part of FunnelIQ works without it."
        )
    try:
        import crewai  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on the deployed image
        return f"CrewAI is not installed or failed to load on this server: {exc}"
    return None


def build_llm(model: str | None = None):  # type: ignore[no-untyped-def]
    """The configured Claude model, or raise `CrewUnavailable` with the reason."""
    reason = unavailable_reason()
    if reason:
        raise CrewUnavailable(reason)

    from crewai import LLM

    return LLM(model=model or DEFAULT_MODEL, api_key=api_key(), temperature=0.1)
