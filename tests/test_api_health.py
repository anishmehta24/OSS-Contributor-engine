"""GET /health returns ok + service-config flags."""
from __future__ import annotations

import pytest


@pytest.mark.unit
def test_health_reports_all_services_unconfigured_by_default(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    services = body["services"]
    assert services["github"] is False
    assert services["embedder"] is False
    assert services["llm_router"] is False
    # voyage is kept as a back-compat alias
    assert services["voyage"] is False


@pytest.mark.unit
def test_health_reflects_configured_services(client, api_app):
    api_app.state.github = object()
    api_app.state.embedder = object()
    api_app.state.voyage = api_app.state.embedder  # alias
    api_app.state.llm_router = object()
    response = client.get("/health")
    services = response.json()["services"]
    assert services["github"] is True
    assert services["embedder"] is True
    assert services["voyage"] is True
    assert services["llm_router"] is True


@pytest.mark.unit
def test_openapi_docs_load(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    paths = spec["paths"]
    assert "/health" in paths
    assert "/auth/login" in paths
    assert "/auth/callback" in paths
    assert "/auth/me" in paths
    assert "/users/me/profile" in paths
    assert "/users/me" in paths
    assert "/users/me/matches" in paths
    assert "/admin/stats" in paths
