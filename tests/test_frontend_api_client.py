"""Tests for the Streamlit frontend's HTTP wrapper."""
from __future__ import annotations

import httpx
import pytest
import respx

from frontend.api_client import ApiClient, ApiError

BASE = "http://test.local"


@pytest.fixture
def client():
    c = ApiClient(base_url=BASE)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
@respx.mock
def test_api_error_carries_status_and_message(client):
    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(503, json={"detail": "GitHub not configured"})
    )
    with pytest.raises(ApiError) as exc_info:
        client.health()
    assert exc_info.value.status_code == 503
    assert "GitHub" in exc_info.value.message


@pytest.mark.unit
@respx.mock
def test_api_error_with_non_json_body(client):
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(ApiError) as exc_info:
        client.health()
    assert exc_info.value.status_code == 500
    assert "boom" in exc_info.value.message


# ---------------------------------------------------------------------------
# Endpoint coverage
# ---------------------------------------------------------------------------

@pytest.mark.unit
@respx.mock
def test_health_returns_services(client):
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(
        200, json={"status": "ok", "version": "0.1.0",
                   "services": {"github": True, "voyage": True, "llm_router": True}},
    ))
    h = client.health()
    assert h["status"] == "ok"
    assert h["services"]["github"] is True


@pytest.mark.unit
@respx.mock
def test_profile_me_unwraps_profile_key(client):
    respx.post(f"{BASE}/users/me/profile").mock(return_value=httpx.Response(
        201, json={"profile": {"github_login": "x", "languages": ["Python"]}},
    ))
    p = client.profile_me()
    assert p["github_login"] == "x"
    assert p["languages"] == ["Python"]


@pytest.mark.unit
@respx.mock
def test_get_my_profile_returns_none_on_409(client):
    respx.get(f"{BASE}/users/me").mock(return_value=httpx.Response(409, json={}))
    assert client.get_my_profile() is None


@pytest.mark.unit
@respx.mock
def test_get_my_matches_passes_query_params(client):
    route = respx.get(f"{BASE}/users/me/matches").mock(return_value=httpx.Response(
        200, json={"github_login": "me", "count": 0, "matches": []},
    ))
    client.get_my_matches(top=5, difficulty="easy", explain=False)
    request = route.calls[0].request
    qs = dict(request.url.params)
    assert qs["top"] == "5"
    assert qs["difficulty"] == "easy"
    assert qs["explain"] == "false"
    # Default mode is general
    assert qs["mode"] == "general"


@pytest.mark.unit
@respx.mock
def test_get_my_matches_sends_gsoc_mode(client):
    route = respx.get(f"{BASE}/users/me/matches").mock(return_value=httpx.Response(
        200, json={"github_login": "me", "count": 0, "matches": []},
    ))
    client.get_my_matches(mode="gsoc")
    assert dict(route.calls[0].request.url.params)["mode"] == "gsoc"


@pytest.mark.unit
@respx.mock
def test_create_investigation_returns_job_id(client):
    respx.post(f"{BASE}/investigations").mock(return_value=httpx.Response(
        202, json={"job_id": "abc-123", "status": "queued"},
    ))
    job_id = client.create_investigation(repo="x/y", issue_number=1)
    assert job_id == "abc-123"


@pytest.mark.unit
@respx.mock
def test_me_returns_none_when_unauthenticated(client):
    respx.get(f"{BASE}/auth/me").mock(return_value=httpx.Response(401))
    assert client.me() is None


@pytest.mark.unit
@respx.mock
def test_me_returns_user_when_authenticated(client):
    respx.get(f"{BASE}/auth/me").mock(return_value=httpx.Response(
        200, json={"id": 1, "github_login": "dev", "github_id": 42,
                   "name": None, "has_oauth_token": True},
    ))
    body = client.me()
    assert body["github_login"] == "dev"


# ---------------------------------------------------------------------------
# Session cookie handling (Batch 15)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_constructor_accepts_session_cookie():
    c = ApiClient(base_url=BASE, session_cookie="signed-value-here")
    assert c.has_session
    c.close()


@pytest.mark.unit
def test_set_and_clear_session(client):
    assert not client.has_session
    client.set_session("abc.def")
    assert client.has_session
    client.clear_session()
    assert not client.has_session


@pytest.mark.unit
@respx.mock
def test_session_cookie_is_sent_on_requests():
    route = respx.get(f"{BASE}/auth/me").mock(return_value=httpx.Response(
        200, json={"id": 1, "github_login": "x", "github_id": 1,
                   "name": None, "has_oauth_token": True},
    ))
    c = ApiClient(base_url=BASE, session_cookie="my-signed-token")
    c.me()
    sent_cookies = route.calls[0].request.headers.get("cookie", "")
    assert "oss_engine_session=my-signed-token" in sent_cookies
    c.close()


@pytest.mark.unit
@respx.mock
def test_get_investigation_returns_row(client):
    respx.get(f"{BASE}/investigations/abc").mock(return_value=httpx.Response(
        200, json={"id": "abc", "status": "completed", "markdown_report": "# r"},
    ))
    row = client.get_investigation("abc")
    assert row["status"] == "completed"


@pytest.mark.unit
@respx.mock
def test_draft_pitch_default_no_force_query(client):
    route = respx.post(f"{BASE}/investigations/abc/pitch").mock(return_value=httpx.Response(
        200, json={"investigation_id": "abc", "comment_md": "x",
                   "asks_questions": False, "tone": "respectful", "cached": False},
    ))
    pitch = client.draft_pitch("abc")
    assert pitch["comment_md"] == "x"
    # Default call sends no force= param
    assert "force" not in dict(route.calls[0].request.url.params)


@pytest.mark.unit
@respx.mock
def test_draft_pitch_force_sends_query(client):
    route = respx.post(f"{BASE}/investigations/abc/pitch").mock(return_value=httpx.Response(
        200, json={"investigation_id": "abc", "comment_md": "x",
                   "asks_questions": False, "tone": "respectful", "cached": False},
    ))
    client.draft_pitch("abc", force=True)
    assert dict(route.calls[0].request.url.params)["force"] == "true"


@pytest.mark.unit
@respx.mock
def test_global_cost_returns_summary(client):
    respx.get(f"{BASE}/admin/cost").mock(return_value=httpx.Response(
        200, json={"scope": "global", "total_calls": 7, "total_tokens_in": 100,
                   "total_tokens_out": 50, "total_cost_usd": 0.001,
                   "total_latency_ms": 200, "total_errors": 0, "per_agent": []},
    ))
    c = client.global_cost()
    assert c["total_calls"] == 7
    assert c["scope"] == "global"


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------

@pytest.mark.unit
@respx.mock
def test_stream_investigation_yields_parsed_events(client):
    sse_body = (
        "data: {\"type\": \"queued\"}\n\n"
        ": heartbeat\n\n"
        "data: {\"type\": \"agent_started\", \"agent\": \"issue_analyst\"}\n\n"
        "data: {\"type\": \"investigation_completed\", \"investigation_id\": \"x\"}\n\n"
    )
    respx.get(f"{BASE}/investigations/abc/stream").mock(
        return_value=httpx.Response(
            200, text=sse_body,
            headers={"content-type": "text/event-stream"},
        )
    )
    events = list(client.stream_investigation("abc"))
    types = [e["type"] for e in events]
    assert types == ["queued", "agent_started", "investigation_completed"]


@pytest.mark.unit
@respx.mock
def test_stream_skips_malformed_json(client):
    sse_body = (
        "data: not json\n\n"
        "data: {\"type\": \"investigation_completed\"}\n\n"
    )
    respx.get(f"{BASE}/investigations/abc/stream").mock(
        return_value=httpx.Response(200, text=sse_body)
    )
    events = list(client.stream_investigation("abc"))
    assert len(events) == 1
    assert events[0]["type"] == "investigation_completed"


@pytest.mark.unit
@respx.mock
def test_stream_stops_after_terminal_event(client):
    sse_body = (
        "data: {\"type\": \"investigation_failed\", \"error\": \"x\"}\n\n"
        "data: {\"type\": \"should_not_see\"}\n\n"
    )
    respx.get(f"{BASE}/investigations/abc/stream").mock(
        return_value=httpx.Response(200, text=sse_body)
    )
    events = list(client.stream_investigation("abc"))
    assert len(events) == 1
    assert events[0]["type"] == "investigation_failed"
