"""Phase 0 acceptance: the skeleton serves a health check.

Trivial by design. Its job is to prove the CI pipeline and the app wiring both
work before any real code depends on them.
"""

from fastapi.testclient import TestClient

from funneliq.api.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "funneliq"


def test_health_reports_uptime_and_commit() -> None:
    """These two fields are what make /health useful for restart verification."""
    body = client.get("/health").json()

    assert body["uptime_seconds"] >= 0
    assert isinstance(body["commit"], str)
