"""Run lifecycle: persistence, restart, idempotency, cancellation, capacity, and event limits."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from predixion.contracts import EventType, Mode, ResearchRequest, RunStatus, StopReason
from predixion.fixtures import FixtureExtract, FixtureModel, FixtureSearch
from predixion.orchestrator import Providers
from predixion.runs import ActiveRun, RunError, RunManager, wait_for
from predixion.store import Store

from .conftest import SlowSearch, make_settings, scenario

QUESTION = scenario("agent_memory").question
OWNER = "local"


def _manager(**overrides) -> RunManager:
    return RunManager(make_settings(**overrides), Store(":memory:"))


def _slow(manager: RunManager, monkeypatch: pytest.MonkeyPatch) -> SlowSearch:
    sc = scenario("agent_memory")
    search = SlowSearch(sc)
    providers = Providers(search, FixtureExtract(sc), FixtureModel(sc), Mode.fixture)
    monkeypatch.setattr(manager, "_providers", lambda mode, question: providers)
    return search


async def _events(manager: RunManager, run_id: str, owner: str = OWNER, after: int = 0):
    return [e async for e in manager.stream(run_id, owner, after) if e is not None]


# ---------------------------------------------------------------------------
# Store


def test_restart_marks_abandoned_runs_interrupted(tmp_path) -> None:
    path = str(tmp_path / "runs.db")
    store = Store(path)
    store.create_run(run_id="run_a", owner=OWNER, question=QUESTION, mode=Mode.fixture, idempotency_key=None, request_hash="h")
    store.create_run(run_id="run_b", owner=OWNER, question=QUESTION, mode=Mode.fixture, idempotency_key=None, request_hash="h")
    store.set_status("run_a", RunStatus.running)
    store.set_status("run_b", RunStatus.completed)
    store.close()

    reopened = Store(path)
    assert reopened.mark_interrupted() == ["run_a"]
    view = reopened.get_run("run_a", OWNER)
    assert view is not None
    assert (view.status, view.stop_reason) == (RunStatus.interrupted, StopReason.process_interrupted)
    assert view.error
    assert reopened.get_status("run_b", OWNER) == RunStatus.completed
    # A reconnecting event stream ends on this terminal event instead of waiting.
    last = reopened.events_after("run_a", 0)[-1]
    assert last.type.value == "status" and last.data == {
        "status": "interrupted",
        "stop_reason": "process_interrupted",
        "terminal": True,
    }
    assert reopened.events_after("run_b", 0) == []


async def test_manager_start_recovers_after_restart(tmp_path) -> None:
    path = str(tmp_path / "runs.db")
    store = Store(path)
    store.create_run(run_id="run_a", owner=OWNER, question=QUESTION, mode=Mode.fixture, idempotency_key=None, request_hash="h")
    store.close()

    manager = RunManager(make_settings(), Store(path))
    await manager.start()
    try:
        assert manager.store.get_status("run_a", OWNER) == RunStatus.interrupted
    finally:
        await manager.shutdown()


def test_purge_removes_only_old_terminal_runs() -> None:
    store = Store(":memory:")
    for run_id, status in (("run_old", RunStatus.completed), ("run_new", RunStatus.completed), ("run_live", RunStatus.running)):
        store.create_run(run_id=run_id, owner=OWNER, question=QUESTION, mode=Mode.fixture, idempotency_key=None, request_hash="h")
        store.set_status(run_id, status)
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    store._conn.execute("UPDATE runs SET updated_at = ? WHERE run_id IN ('run_old', 'run_live')", (old,))
    assert store.purge_expired(30) == 1
    assert store.get_status("run_old", OWNER) is None
    assert store.get_status("run_new", OWNER) == RunStatus.completed
    assert store.get_status("run_live", OWNER) == RunStatus.running


# ---------------------------------------------------------------------------
# Runs through the manager


async def test_fixture_run_streams_events_and_stores_report() -> None:
    manager = _manager()
    started = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)
    assert started.status == RunStatus.queued and not started.reused
    events = await _events(manager, started.run_id)
    await wait_for(manager, started.run_id)

    seqs = [e.seq for e in events]
    assert seqs == sorted(set(seqs)) and seqs[0] == 1
    assert events[-1].type == EventType.status and events[-1].data and events[-1].data["terminal"]
    assert any(e.type == EventType.report for e in events)

    view = manager.store.get_run(started.run_id, OWNER)
    assert view is not None and view.report is not None
    assert view.status == RunStatus.completed
    assert view.last_event_seq == seqs[-1]

    # Reconnect: replay only what came after the last seen event.
    resumed = await _events(manager, started.run_id, after=3)
    assert [e.seq for e in resumed] == seqs[3:]


async def test_other_owners_cannot_see_a_run() -> None:
    manager = _manager()
    started = manager.start_run(ResearchRequest(question=QUESTION), owner="alice")
    assert await _events(manager, started.run_id, owner="bob") == []
    await wait_for(manager, started.run_id)
    assert manager.store.get_run(started.run_id, "bob") is None
    assert manager.cancel(started.run_id, "bob") is None
    assert not manager.delete(started.run_id, "bob")
    assert manager.store.get_run(started.run_id, "alice") is not None


async def test_idempotency_is_scoped_to_owner_and_request() -> None:
    manager = _manager()
    request = ResearchRequest(question=QUESTION)
    first = manager.start_run(request, owner="alice", idempotency_key="key-1")
    again = manager.start_run(request, owner="alice", idempotency_key="key-1")
    assert again.run_id == first.run_id and again.reused

    with pytest.raises(RunError) as info:
        manager.start_run(ResearchRequest(question=QUESTION, max_rounds=1), owner="alice", idempotency_key="key-1")
    assert info.value.code == "idempotency_conflict"

    other = manager.start_run(request, owner="bob", idempotency_key="key-1")
    assert other.run_id != first.run_id
    for run_id in (first.run_id, other.run_id):
        await wait_for(manager, run_id)


async def test_live_mode_without_keys_is_refused() -> None:
    manager = _manager()
    with pytest.raises(RunError) as info:
        manager.start_run(ResearchRequest(question=QUESTION, mode="live"), owner=OWNER)
    assert info.value.code == "live_unavailable"
    assert "OPENAI_API_KEY" in info.value.message


async def test_cancel_stops_a_running_run(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager()
    search = _slow(manager, monkeypatch)
    started = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)
    await asyncio.wait_for(search.started.wait(), timeout=10)

    with pytest.raises(RunError) as info:
        manager.delete(started.run_id, OWNER)
    assert info.value.code == "run_active"

    assert manager.cancel(started.run_id, OWNER) == RunStatus.running
    await wait_for(manager, started.run_id)
    view = manager.store.get_run(started.run_id, OWNER)
    assert view is not None and view.report is not None
    assert (view.status, view.stop_reason) == (RunStatus.cancelled, StopReason.cancelled_by_user)
    messages = [e.message for e in manager.store.events_after(started.run_id, 0)]
    assert "Cancellation requested" in messages
    assert messages[-1] == "Run cancelled"

    assert manager.cancel(started.run_id, OWNER) == RunStatus.cancelled  # repeat cancel is harmless
    assert manager.delete(started.run_id, OWNER)
    assert manager.store.get_run(started.run_id, OWNER) is None


async def test_queued_run_keeps_its_full_time_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run built while queued must not spend its deadline (or report duration) waiting for a slot."""
    manager = _manager(MAX_CONCURRENT_RUNS=1, MAX_QUEUED_RUNS=2)
    sc = scenario("agent_memory")
    slow = Providers(SlowSearch(sc, delay_s=1.0), FixtureExtract(sc), FixtureModel(sc), Mode.fixture)
    fast = Providers(FixtureSearch(sc), FixtureExtract(sc), FixtureModel(sc), Mode.fixture)
    providers = iter([slow, fast])
    monkeypatch.setattr(manager, "_providers", lambda mode, question: next(providers))
    first = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)
    second = manager.start_run(ResearchRequest(question=f"{QUESTION} (queued)"), owner=OWNER)
    research = manager._active[second.run_id].research
    await wait_for(manager, second.run_id)
    view = manager.store.get_run(second.run_id, OWNER)
    assert view is not None and view.report is not None and view.status == RunStatus.completed
    assert view.report.execution.metrics.duration_ms < 1000  # the queue wait is not counted
    assert research.deadline.elapsed() < 1.0
    await wait_for(manager, first.run_id)


async def test_capacity_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(MAX_CONCURRENT_RUNS=1, MAX_QUEUED_RUNS=0)
    search = _slow(manager, monkeypatch)
    started = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)
    await asyncio.wait_for(search.started.wait(), timeout=10)
    with pytest.raises(RunError) as info:
        manager.start_run(ResearchRequest(question=f"{QUESTION} (second)"), owner=OWNER)
    assert info.value.code == "capacity"
    manager.cancel(started.run_id, OWNER)
    await wait_for(manager, started.run_id)


async def test_shutdown_interrupts_active_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager()
    search = _slow(manager, monkeypatch)
    started = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)
    await asyncio.wait_for(search.started.wait(), timeout=10)
    await manager.shutdown()
    view = manager.store.get_run(started.run_id, OWNER)
    assert view is not None
    assert (view.status, view.stop_reason) == (RunStatus.interrupted, StopReason.process_interrupted)
    assert view.report is not None


async def test_event_cap_keeps_terminal_events() -> None:
    manager = _manager(MAX_EVENTS_PER_RUN=50)
    manager.store.create_run(
        run_id="run_x", owner=OWNER, question=QUESTION, mode=Mode.fixture, idempotency_key=None, request_hash="h"
    )
    active = ActiveRun(run_id="run_x", owner=OWNER)
    for i in range(100):
        manager._emit(active, EventType.tool, None, f"step {i}", None)
    manager._emit(active, EventType.report, None, "Report ready", {"status": "completed"})
    manager._emit(active, EventType.status, None, "Run completed", {"status": "completed", "terminal": True})

    stored = manager.store.events_after("run_x", 0)
    assert len(stored) == 50
    assert active.dropped_events == 52
    assert [e.type for e in stored[-2:]] == [EventType.report, EventType.status]
