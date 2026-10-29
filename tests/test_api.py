"""HTTP API: run lifecycle, SSE, errors, ownership, and response headers."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from predixion.api import create_app, hash_token
from predixion.contracts import Mode
from predixion.fixtures import FixtureExtract, FixtureModel
from predixion.orchestrator import Providers
from predixion.runs import RunManager

from .conftest import SlowSearch, fixture_providers, make_settings, scenario

QUESTION = scenario("agent_memory").question
UNKNOWN_RUN = "run_" + "f" * 24


def _client(**overrides) -> TestClient:
    return TestClient(create_app(make_settings(**overrides)))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _client(ENABLE_FAULT_INJECTION=True) as c:
        yield c


def _sse(
    client: TestClient, run_id: str, headers: dict[str, str] | None = None, after: int | None = None
) -> tuple[str, list[dict]]:
    """Reads the event stream to its end (the terminal status event)."""
    params = {"after": after} if after is not None else None
    with client.stream("GET", f"/api/runs/{run_id}/events", headers=headers, params=params) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = response.read().decode()
    events = []
    for block in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "data" in fields:
            events.append({"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])})
    return text, events


def _start(client: TestClient, body: dict | None = None, headers: dict[str, str] | None = None) -> str:
    response = client.post("/api/runs", json=body or {"question": QUESTION}, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def _error_code(response) -> str:
    return response.json()["error"]["code"]


# ---------------------------------------------------------------------------
# Health, config, headers


def test_health_and_config(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
    config = client.get("/api/config").json()
    assert config["default_mode"] == "fixture"
    assert config["live_available"] is False
    assert len(client.get("/api/samples").json()) >= 4


def test_security_headers(client: TestClient) -> None:
    response = client.get("/api/config")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# Run lifecycle


def test_run_streams_events_and_returns_report(client: TestClient) -> None:
    run_id = _start(client)
    text, events = _sse(client, run_id)
    assert text.startswith("retry: 3000")
    ids = [e["id"] for e in events]
    assert ids == sorted(set(ids))
    assert events[-1]["event"] == "status" and events[-1]["data"]["data"]["terminal"]
    assert "report" in {e["event"] for e in events}

    view = client.get(f"/api/runs/{run_id}").json()
    assert view["status"] == "completed"
    assert view["report"]["short_answer"]["text"]
    assert run_id in [r["run_id"] for r in client.get("/api/runs").json()]

    # Reconnect with Last-Event-ID replays only later events.
    _, resumed = _sse(client, run_id, headers={"Last-Event-ID": "3"})
    assert [e["id"] for e in resumed] == ids[3:]
    _, resumed = _sse(client, run_id, after=ids[-2])
    assert [e["id"] for e in resumed] == ids[-1:]


def test_export_formats(client: TestClient) -> None:
    run_id = _start(client)
    _sse(client, run_id)
    md = client.get(f"/api/runs/{run_id}/export", params={"format": "md"})
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    assert f'filename="predixion-{run_id}.md"' in md.headers["content-disposition"]
    assert "Fixture" in md.text
    data = client.get(f"/api/runs/{run_id}/export", params={"format": "json"}).json()
    assert data["run_id"] == run_id
    assert client.get(f"/api/runs/{run_id}/export", params={"format": "html"}).status_code == 422


def test_idempotency_key(client: TestClient) -> None:
    headers = {"Idempotency-Key": "abc-123"}
    first = client.post("/api/runs", json={"question": QUESTION}, headers=headers).json()
    again = client.post("/api/runs", json={"question": QUESTION}, headers=headers)
    assert again.status_code == 202
    assert again.json()["run_id"] == first["run_id"] and again.json()["reused"]
    conflict = client.post("/api/runs", json={"question": QUESTION, "max_rounds": 1}, headers=headers)
    assert conflict.status_code == 409 and _error_code(conflict) == "idempotency_conflict"
    bad_key = client.post("/api/runs", json={"question": QUESTION}, headers={"Idempotency-Key": "x" * 200})
    assert bad_key.status_code == 422
    _sse(client, first["run_id"])


def test_cancel_and_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    sc = scenario("agent_memory")
    providers = Providers(SlowSearch(sc), FixtureExtract(sc), FixtureModel(sc), Mode.fixture)
    monkeypatch.setattr(RunManager, "_providers", lambda self, mode, question: providers)
    with _client() as client:
        run_id = _start(client)
        not_ready = client.get(f"/api/runs/{run_id}/export")
        assert not_ready.status_code == 409 and _error_code(not_ready) == "report_not_ready"
        active_delete = client.delete(f"/api/runs/{run_id}")
        assert active_delete.status_code == 409 and _error_code(active_delete) == "run_active"

        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
        _, events = _sse(client, run_id)
        assert events[-1]["data"]["data"]["status"] == "cancelled"
        view = client.get(f"/api/runs/{run_id}").json()
        assert (view["status"], view["stop_reason"]) == ("cancelled", "cancelled_by_user")
        assert client.get(f"/api/runs/{run_id}/export").status_code == 200

        assert client.delete(f"/api/runs/{run_id}").status_code == 204
        assert client.get(f"/api/runs/{run_id}").status_code == 404


# ---------------------------------------------------------------------------
# Request errors


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"question": "short"}, 422, "invalid_request"),
        ({"question": QUESTION, "max_rounds": 9}, 422, "invalid_request"),
        ({"question": QUESTION, "extra": 1}, 422, "invalid_request"),
        ({"question": QUESTION, "seed_urls": ["http://127.0.0.1/admin"]}, 422, "unsafe_url"),
        ({"question": QUESTION, "seed_urls": ["javascript:alert(1)"]}, 422, "unsafe_url"),
        ({"question": QUESTION, "mode": "live"}, 503, "live_unavailable"),
    ],
)
def test_rejected_requests(client: TestClient, body: dict, status: int, code: str) -> None:
    response = client.post("/api/runs", json=body)
    assert response.status_code == status
    assert _error_code(response) == code
    assert response.json()["error"]["message"]


def test_oversized_body(client: TestClient) -> None:
    response = client.post(
        "/api/runs", content=b'{"question": "' + b"x" * 70_000 + b'"}', headers={"content-type": "application/json"}
    )
    assert response.status_code == 413 and _error_code(response) == "body_too_large"


def test_unknown_and_malformed_run_ids(client: TestClient) -> None:
    for path in (
        f"/api/runs/{UNKNOWN_RUN}",
        "/api/runs/not-a-run",
        "/api/runs/run_..%2F..%2Fetc",
        f"/api/runs/{UNKNOWN_RUN}/events",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert _error_code(response) == "not_found"
    assert client.post(f"/api/runs/{UNKNOWN_RUN}/cancel").status_code == 404
    assert client.delete(f"/api/runs/{UNKNOWN_RUN}").status_code == 404


def test_fault_injection_is_refused_when_disabled() -> None:
    with _client() as client:
        response = client.post("/api/runs", json={"question": QUESTION, "fault": {"search": "unavailable"}})
    assert response.status_code == 403 and _error_code(response) == "fault_injection_disabled"


def test_fault_injection_produces_failed_report(client: TestClient) -> None:
    run_id = _start(client, {"question": QUESTION, "fault": {"search": "auth"}})
    _sse(client, run_id)
    view = client.get(f"/api/runs/{run_id}").json()
    assert (view["status"], view["stop_reason"]) == ("failed", "provider_auth_error")


# ---------------------------------------------------------------------------
# Token auth and ownership


def test_token_auth_scopes_runs_to_their_owner() -> None:
    hashes = f"alice:{hash_token('alice-token')},bob:{hash_token('bob-token')}"
    alice = {"Authorization": "Bearer alice-token"}
    bob = {"Authorization": "Bearer bob-token"}
    with _client(AUTH_MODE="token", API_TOKEN_HASHES=hashes) as client:
        missing = client.get("/api/config")
        assert missing.status_code == 401 and missing.headers["www-authenticate"] == "Bearer"
        assert client.get("/api/config", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/healthz").status_code == 200  # probes stay open

        run_id = _start(client, headers=alice)
        _sse(client, run_id, headers=alice)
        assert client.get(f"/api/runs/{run_id}", headers=alice).status_code == 200
        assert client.get(f"/api/runs/{run_id}", headers=bob).status_code == 404
        assert client.get(f"/api/runs/{run_id}/events", headers=bob).status_code == 404
        assert client.delete(f"/api/runs/{run_id}", headers=bob).status_code == 404
        assert client.get("/api/runs", headers=bob).json() == []


def test_token_mode_requires_hashes() -> None:
    with pytest.raises(RuntimeError):
        create_app(make_settings(AUTH_MODE="token"))


# ---------------------------------------------------------------------------
# Public access for visitors without a token

ALICE = {"Authorization": "Bearer alice-token"}
VISITOR_A = {"X-Visitor-Id": "a" * 32}
VISITOR_B = {"X-Visitor-Id": "b" * 32}
FAKE_KEYS = {"OPENAI_API_KEY": "test-openai-key", "TAVILY_API_KEY": "test-tavily-key"}


def _public_client(monkeypatch: pytest.MonkeyPatch, access: str, **overrides) -> TestClient:
    """Token mode with live credentials configured; live runs use fixture providers, so nothing leaves the test."""
    sc = scenario("agent_memory")
    monkeypatch.setattr(RunManager, "_providers", lambda self, mode, question: fixture_providers(sc))
    hashes = f"alice:{hash_token('alice-token')}"
    return _client(AUTH_MODE="token", API_TOKEN_HASHES=hashes, PUBLIC_ACCESS=access, **FAKE_KEYS, **overrides)


def test_public_fixture_access_scopes_visitors_and_keeps_live_behind_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    with _public_client(monkeypatch, "fixture", PREDIXION_MODE="live") as client:
        config = client.get("/api/config", headers=VISITOR_A).json()
        assert (config["live_available"], config["live_needs_token"], config["default_mode"]) == (True, True, "fixture")
        assert client.get("/api/config", headers=ALICE).json()["live_needs_token"] is False

        run_id = _start(client, {"question": QUESTION, "mode": "fixture"}, headers=VISITOR_A)
        _sse(client, run_id, headers=VISITOR_A)
        assert client.get(f"/api/runs/{run_id}", headers=VISITOR_A).json()["status"] == "completed"
        assert client.get(f"/api/runs/{run_id}/export", headers=VISITOR_A).status_code == 200
        for other in (VISITOR_B, ALICE):
            assert client.get(f"/api/runs/{run_id}", headers=other).status_code == 404
            assert client.get(f"/api/runs/{run_id}/events", headers=other).status_code == 404
            assert client.get(f"/api/runs/{run_id}/export", headers=other).status_code == 404
            assert client.post(f"/api/runs/{run_id}/cancel", headers=other).status_code == 404
            assert client.delete(f"/api/runs/{run_id}", headers=other).status_code == 404
            assert client.get("/api/runs", headers=other).json() == []

        for body in ({"question": QUESTION, "mode": "live"}, {"question": QUESTION}):  # the server default is live
            refused = client.post("/api/runs", json=body, headers=VISITOR_A)
            assert refused.status_code == 401 and _error_code(refused) == "live_requires_token"
        assert _start(client, {"question": QUESTION, "mode": "live"}, headers=ALICE)


def test_public_access_still_rejects_bad_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    with _public_client(monkeypatch, "fixture") as client:
        assert client.get("/api/config").status_code == 401
        assert client.get("/api/config", headers={"X-Visitor-Id": "too-short"}).status_code == 401
        assert client.get("/api/config", headers={"X-Visitor-Id": "a" * 31 + "!"}).status_code == 401
        # A wrong token is refused, not downgraded to visitor access.
        assert client.get("/api/config", headers={"Authorization": "Bearer wrong", **VISITOR_A}).status_code == 401


def test_public_live_access_lets_visitors_run_live(monkeypatch: pytest.MonkeyPatch) -> None:
    with _public_client(monkeypatch, "live") as client:
        assert client.get("/api/config", headers=VISITOR_A).json()["live_needs_token"] is False
        run_id = _start(client, {"question": QUESTION, "mode": "live"}, headers=VISITOR_A)
        _sse(client, run_id, headers=VISITOR_A)
        assert client.get(f"/api/runs/{run_id}", headers=VISITOR_A).json()["mode"] == "live"
        assert client.get(f"/api/runs/{run_id}", headers=VISITOR_B).status_code == 404


def test_public_access_requires_token_mode() -> None:
    with pytest.raises(RuntimeError):
        create_app(make_settings(PUBLIC_ACCESS="fixture"))


def test_live_run_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    live = {"question": QUESTION, "mode": "live"}
    with _public_client(monkeypatch, "live", LIVE_RUNS_PER_USER_PER_HOUR=2, LIVE_RUNS_PER_DAY=3) as client:
        _start(client, live, headers={**VISITOR_A, "Idempotency-Key": "k1"})
        _start(client, live, headers={**VISITOR_A, "Idempotency-Key": "k1"})  # a replay is not a new run
        _start(client, live, headers=VISITOR_A)
        hourly = client.post("/api/runs", json=live, headers=VISITOR_A)
        assert hourly.status_code == 429 and _error_code(hourly) == "rate_limited"
        assert 3000 < int(hourly.headers["retry-after"]) <= 3600
        _start(client, {"question": QUESTION, "mode": "fixture"}, headers=VISITOR_A)  # fixture runs are not limited

        _start(client, live, headers=VISITOR_B)
        daily = client.post("/api/runs", json=live, headers=ALICE)
        assert daily.status_code == 429 and _error_code(daily) == "rate_limited"
        assert int(daily.headers["retry-after"]) > 80_000


def test_daily_live_limit_survives_a_restart_through_the_ledger(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps([time.time() - 90_000]))  # older than a day: no longer counts
    live = {"question": QUESTION, "mode": "live"}
    with _public_client(monkeypatch, "live", LIVE_RUNS_PER_DAY=2, LIVE_LEDGER_PATH=str(ledger)) as client:
        _start(client, live, headers=VISITOR_A)
        _start(client, live, headers=VISITOR_B)
    assert len(json.loads(ledger.read_text())) == 2

    with _public_client(monkeypatch, "live", LIVE_RUNS_PER_DAY=2, LIVE_LEDGER_PATH=str(ledger)) as client:
        refused = client.post("/api/runs", json=live, headers=ALICE)
        assert refused.status_code == 429 and _error_code(refused) == "rate_limited"


@pytest.mark.parametrize("broken", ["unwritable", "damaged"])
def test_live_runs_are_refused_when_the_ledger_is_unusable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, broken: str) -> None:
    if broken == "unwritable":
        ledger = tmp_path / "missing-dir" / "ledger.json"
    else:
        ledger = tmp_path / "ledger.json"
        ledger.write_text("[1, 2")  # a damaged file must not reset the daily count
    with _public_client(monkeypatch, "live", LIVE_RUNS_PER_DAY=5, LIVE_LEDGER_PATH=str(ledger)) as client:
        refused = client.post("/api/runs", json={"question": QUESTION, "mode": "live"}, headers=VISITOR_A)
        assert refused.status_code == 503 and _error_code(refused) == "live_unavailable"
        _start(client, {"question": QUESTION, "mode": "fixture"}, headers=VISITOR_A)


def test_hsts_is_sent_only_when_configured(client: TestClient) -> None:
    assert "strict-transport-security" not in client.get("/healthz").headers
    with _client(HSTS_MAX_AGE_S=31536000) as hsts:
        assert hsts.get("/healthz").headers["strict-transport-security"] == "max-age=31536000"
