"""Run lifecycle: admission, execution, events, cancellation, and persistence.

Each run is an asyncio task in this process. Events go to SQLite (so a
reconnecting client can replay them) and to in-memory subscriber queues (so
live clients see them without polling). The orchestrator never emits the final
report event; the manager does, after the report is stored, so a client that
sees the terminal status can always fetch the full report.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .contracts import (
    TERMINAL_STATUSES,
    EventType,
    Mode,
    ResearchReport,
    ResearchRequest,
    RunEvent,
    RunStatus,
    Stage,
    StartRunResponse,
    StopReason,
)
from .fixtures import FixtureExtract, FixtureModel, FixtureSearch, match_scenario
from .llm import GroqModel, ModelRoutes, OpenAIModel, live_routes
from .logs import error_location, log
from .orchestrator import Providers, ResearchRun
from .store import Store
from .tools import TavilyClient, TTLCache

logger = logging.getLogger("predixion.runs")

# Extra time beyond the run deadline before the manager stops waiting for the orchestrator.
HARD_TIMEOUT_GRACE_S = 15.0
PURGE_INTERVAL_S = 3600.0


class RunError(Exception):
    """A request the manager refuses. `code` maps to an HTTP status in the API layer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class StreamSlot:
    """One event-stream connection's share of the stream limits. `release` is idempotent: both the
    response body's `finally` and the response's background task call it, whichever runs."""

    def __init__(self, manager: RunManager, run_id: str) -> None:
        self._manager, self.run_id, self._released = manager, run_id, False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._manager._release_stream(self.run_id)


@dataclass
class ActiveRun:
    run_id: str
    owner: str
    research: ResearchRun = field(init=False)
    events: list[RunEvent] = field(default_factory=list)
    subscribers: set[asyncio.Queue[RunEvent | None]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    cancel_requested: bool = False
    shutting_down: bool = False
    seq: int = 0
    dropped_events: int = 0
    done: bool = False


def request_hash(request: ResearchRequest, mode: Mode) -> str:
    body = request.model_dump(mode="json")
    body["mode"] = mode.value
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def new_run_id() -> str:
    return "run_" + secrets.token_hex(12)


class RunManager:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self._active: dict[str, ActiveRun] = {}
        self._slots = asyncio.Semaphore(settings.max_concurrent_runs)
        self._tavily: TavilyClient | None = None
        self._routes: ModelRoutes | None = None
        self._models: list[OpenAIModel | GroqModel] = []
        self._cache = TTLCache(settings.cache_max_entries) if settings.cache_max_entries > 0 else None
        self._purge_task: asyncio.Task[None] | None = None
        self._sse_total = 0
        self._sse_per_run: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Lifecycle

    async def start(self) -> None:
        interrupted = self.store.mark_interrupted()
        if interrupted:
            log(logger, logging.WARNING, "marked runs interrupted after restart", count=len(interrupted))
        purged = self.store.purge_expired(self.settings.retention_days)
        if purged:
            log(logger, logging.INFO, "purged expired runs", count=purged)
        self._purge_task = asyncio.create_task(self._purge_loop())

    async def shutdown(self) -> None:
        if self._purge_task:
            self._purge_task.cancel()
        for run in list(self._active.values()):
            run.shutting_down = True
            if run.task and not run.task.done():
                run.task.cancel()
        tasks = [r.task for r in self._active.values() if r.task]
        if tasks:
            await asyncio.wait(tasks, timeout=5)
        if self._tavily:
            await self._tavily.aclose()
        for model in self._models:
            await model.aclose()

    async def _purge_loop(self) -> None:
        while True:
            await asyncio.sleep(PURGE_INTERVAL_S)
            try:
                count = self.store.purge_expired(self.settings.retention_days)
                if count:
                    log(logger, logging.INFO, "purged expired runs", count=count)
            except Exception:
                logger.exception("retention purge failed")

    # ------------------------------------------------------------------
    # Admission

    def resolve_mode(self, request: ResearchRequest) -> Mode:
        mode = request.mode or Mode(self.settings.mode)
        if mode == Mode.live and not self.settings.live_available:
            missing = ", ".join(self.settings.missing_live_credentials())
            raise RunError("live_unavailable", f"Live mode needs {missing}. Use fixture mode or configure the keys.")
        return mode

    def _providers(self, mode: Mode, question: str) -> Providers:
        if mode == Mode.fixture:
            scenario = match_scenario(question)
            return Providers(
                search=FixtureSearch(scenario),
                extract=FixtureExtract(scenario),
                model=FixtureModel(scenario),
                mode=Mode.fixture,
            )
        if self._tavily is None:
            assert self.settings.tavily_api_key is not None
            self._tavily = TavilyClient(self.settings.tavily_api_key.get_secret_value())
        if self._routes is None:
            self._routes, self._models = live_routes(self.settings)
        return Providers(
            search=self._tavily,
            extract=self._tavily,
            model=self._routes.primary,
            mode=Mode.live,
            cache=self._cache,
            routes=self._routes,
        )

    def start_run(self, request: ResearchRequest, *, owner: str, idempotency_key: str | None = None) -> StartRunResponse:
        mode = self.resolve_mode(request)
        digest = request_hash(request, mode)

        if idempotency_key:
            existing = self.store.find_idempotent(owner, idempotency_key)
            if existing:
                run_id, existing_hash, status = existing
                if existing_hash != digest:
                    raise RunError("idempotency_conflict", "This Idempotency-Key was already used with a different request.")
                return self._start_response(run_id, status, reused=True)

        if len(self._active) >= self.settings.max_concurrent_runs + self.settings.max_queued_runs:
            raise RunError("capacity", "The server is at capacity. Try again shortly.")

        run_id = new_run_id()
        self.store.create_run(
            run_id=run_id,
            owner=owner,
            question=request.question,
            mode=mode,
            idempotency_key=idempotency_key,
            request_hash=digest,
        )
        active = ActiveRun(run_id=run_id, owner=owner)
        # The orchestrator is built before a slot is free, so a queued run can still produce a snapshot report.
        active.research = ResearchRun(
            run_id,
            request,
            self.settings,
            self._providers(mode, request.question),
            lambda t, s, m, d: self._emit(active, t, s, m, d),
        )
        self._active[run_id] = active
        self._emit(active, EventType.status, None, "Run queued", {"status": RunStatus.queued.value, "mode": mode.value})
        active.task = asyncio.create_task(self._run(active), name=run_id)
        active.task.add_done_callback(lambda _t: self._ensure_finished(active))
        log(logger, logging.INFO, "run accepted", run_id=run_id, mode=mode.value, **self._content(question=request.question))
        return self._start_response(run_id, RunStatus.queued, reused=False)

    @staticmethod
    def _start_response(run_id: str, status: RunStatus, *, reused: bool) -> StartRunResponse:
        return StartRunResponse(
            run_id=run_id,
            status=status,
            reused=reused,
            events_url=f"/api/runs/{run_id}/events",
            run_url=f"/api/runs/{run_id}",
        )

    def _content(self, **fields: Any) -> dict[str, Any]:
        return fields if self.settings.log_content else {}

    def _log_error(self, message: str, run_id: str, exc: BaseException) -> None:
        """Error log without exception text: validation and provider errors can quote the request or a page.
        The text is included only when LOG_CONTENT is on."""
        log(
            logger,
            logging.ERROR,
            message,
            run_id=run_id,
            error=type(exc).__name__,
            where=error_location(exc),
            **self._content(detail=str(exc)[:500]),
        )

    # ------------------------------------------------------------------
    # Execution

    async def _run(self, active: ActiveRun) -> None:
        run_id = active.run_id
        report: ResearchReport | None = None
        error: str | None = None
        try:
            async with self._slots:
                if active.cancel_requested:
                    raise asyncio.CancelledError
                self.store.set_status(run_id, RunStatus.running)
                hard_timeout = self.settings.run_deadline_s + HARD_TIMEOUT_GRACE_S
                try:
                    report = await asyncio.wait_for(active.research.execute(), timeout=hard_timeout)
                except TimeoutError:
                    log(logger, logging.WARNING, "run hit hard timeout", run_id=run_id)
                    status = RunStatus.partial if active.research.evidence else RunStatus.failed
                    report = active.research.snapshot_report(
                        status, StopReason.deadline_reached, "The run exceeded its time limit and was stopped."
                    )
        except asyncio.CancelledError:
            if active.shutting_down and not active.cancel_requested:
                report = active.research.snapshot_report(
                    RunStatus.interrupted, StopReason.process_interrupted, "The server shut down while the run was active."
                )
                error = "The server shut down while this run was active."
            else:
                report = active.research.snapshot_report(
                    RunStatus.cancelled, StopReason.cancelled_by_user, "Cancelled by the user."
                )
        except Exception as exc:
            self._log_error("run failed unexpectedly", run_id, exc)
            error = f"Internal error ({type(exc).__name__})."
            try:
                report = active.research.snapshot_report(RunStatus.failed, StopReason.internal_error, error)
            except Exception as exc2:
                self._log_error("snapshot after failure also failed", run_id, exc2)
                report = None
        finally:
            self._finish(active, report, error)

    def _ensure_finished(self, active: ActiveRun) -> None:
        # A task cancelled before its first step never enters _run, so its finally block never runs.
        if not active.done:
            try:
                report = active.research.snapshot_report(
                    RunStatus.cancelled, StopReason.cancelled_by_user, "Cancelled by the user."
                )
            except Exception as exc:
                self._log_error("snapshot after cancellation failed", active.run_id, exc)
                report = None
            self._finish(active, report, None)

    def _finish(self, active: ActiveRun, report: ResearchReport | None, error: str | None) -> None:
        """Finalize once. Storage failures are logged and reported, never raised: the in-memory run is
        always released, subscribers always get a terminal event, and that event says whether the
        report was saved. A run whose terminal state could not be persisted is marked interrupted at
        the next start, like any run the process left active."""
        if active.done:
            return
        active.done = True
        run_id = active.run_id
        persisted = True
        if report is not None:
            status, stop_reason = report.status, report.stop_reason
            try:
                self.store.save_report(run_id, report)
                if error:
                    self.store.set_status(run_id, status, error=error)
            except Exception as exc:
                persisted = False
                self._log_error("report persist failed", run_id, exc)
                status, stop_reason = RunStatus.failed, StopReason.internal_error
                error = "The run finished, but its report could not be saved."
                try:
                    self.store.set_status(run_id, status, stop_reason=stop_reason, error=error)
                except Exception as exc2:
                    self._log_error("status persist failed", run_id, exc2)
        else:
            status, stop_reason = RunStatus.failed, StopReason.internal_error
            try:
                self.store.set_status(run_id, status, stop_reason=stop_reason, error=error or "The run failed without a report.")
            except Exception as exc:
                persisted = False
                self._log_error("status persist failed", run_id, exc)
        if report is not None and persisted:
            self._emit(
                active,
                EventType.report,
                Stage.finalize,
                "Report ready",
                {
                    "status": status.value,
                    "stop_reason": stop_reason.value if stop_reason else None,
                    "confidence": report.confidence.level.value,
                    "findings": len(report.key_findings),
                    "sources": len(report.sources),
                },
            )
        self._emit(
            active,
            EventType.status,
            None,
            _final_message(status) if persisted else "Run finished, but its report could not be saved",
            {
                "status": status.value,
                "stop_reason": stop_reason.value if stop_reason else None,
                "terminal": True,
                "persisted": persisted,
            },
        )
        for queue in list(active.subscribers):
            try:
                queue.put_nowait(None)
            except Exception as exc:  # a closed or full queue must not stop the other subscribers
                self._log_error("subscriber notify failed", run_id, exc)
        active.subscribers.clear()
        self._active.pop(run_id, None)
        metrics = report.execution.metrics if report else None
        log(
            logger,
            logging.INFO,
            "run finished",
            run_id=run_id,
            status=status.value,
            stop_reason=stop_reason.value if stop_reason else None,
            persisted=persisted,
            duration_ms=metrics.duration_ms if metrics else None,
            model_calls=metrics.model_calls if metrics else None,
            cost_usd=metrics.estimated_cost_usd if metrics else None,
            dropped_events=active.dropped_events,
        )

    # ------------------------------------------------------------------
    # Events

    def _emit(self, active: ActiveRun, type_: EventType, stage: Stage | None, message: str, data: dict[str, Any] | None) -> None:
        terminal = type_ == EventType.report or (type_ == EventType.status and bool(data and data.get("terminal")))
        # Terminal events are always kept so clients can finish; other events stop at the cap.
        if not terminal and active.seq >= self.settings.max_events_per_run - 2:
            active.dropped_events += 1
            return
        active.seq += 1
        event = RunEvent(seq=active.seq, ts=datetime.now(UTC), type=type_, stage=stage, message=message, data=data)
        active.events.append(event)
        try:
            self.store.append_event(active.run_id, event)
        except Exception as exc:
            self._log_error("event persist failed", active.run_id, exc)
        for queue in list(active.subscribers):
            try:
                queue.put_nowait(event)
            except Exception as exc:  # a closed or full queue is dropped; the run and the other clients continue
                active.subscribers.discard(queue)
                self._log_error("subscriber delivery failed", active.run_id, exc)

    def acquire_stream(self, run_id: str) -> StreamSlot:
        if self._sse_total >= self.settings.max_sse_total or self._sse_per_run.get(run_id, 0) >= self.settings.max_sse_per_run:
            raise RunError("too_many_streams", "Too many open event streams. Close one and retry.")
        self._sse_total += 1
        self._sse_per_run[run_id] = self._sse_per_run.get(run_id, 0) + 1
        return StreamSlot(self, run_id)

    def _release_stream(self, run_id: str) -> None:
        self._sse_total = max(0, self._sse_total - 1)
        left = self._sse_per_run.get(run_id, 1) - 1
        if left > 0:
            self._sse_per_run[run_id] = left
        else:
            self._sse_per_run.pop(run_id, None)

    async def stream(self, run_id: str, owner: str, after_seq: int = 0) -> AsyncIterator[RunEvent | None]:
        """Yields events after `after_seq`, then live events until the terminal status. `None` is a keepalive tick."""
        active = self._active.get(run_id)
        if active is not None and active.owner != owner:
            return
        queue: asyncio.Queue[RunEvent | None] | None = None
        if active is not None and not active.done:
            queue = asyncio.Queue()
            active.subscribers.add(queue)  # subscribe first, then replay, so nothing falls in between
        try:
            last = after_seq
            for event in self.store.events_after(run_id, after_seq):
                last = event.seq
                yield event
                if _is_terminal_event(event):
                    return
            if queue is None:
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield None
                    continue
                if item is None:
                    # Run finished; flush anything persisted after our last seen event.
                    for event in self.store.events_after(run_id, last):
                        yield event
                    return
                if item.seq <= last:
                    continue
                last = item.seq
                yield item
                if _is_terminal_event(item):
                    return
        finally:
            if active is not None and queue is not None:
                active.subscribers.discard(queue)

    # ------------------------------------------------------------------
    # Control

    def is_active(self, run_id: str) -> bool:
        return run_id in self._active

    def cancel(self, run_id: str, owner: str) -> RunStatus | None:
        status = self.store.get_status(run_id, owner)
        if status is None:
            return None
        active = self._active.get(run_id)
        if active is None or status in TERMINAL_STATUSES:
            return status
        if not active.cancel_requested:
            active.cancel_requested = True
            self._emit(active, EventType.warning, None, "Cancellation requested", None)
            if active.task and not active.task.done():
                active.task.cancel()
        return status

    def delete(self, run_id: str, owner: str) -> bool:
        if run_id in self._active:
            raise RunError("run_active", "Cancel the run before deleting it.")
        return self.store.delete_run(run_id, owner)


def _is_terminal_event(event: RunEvent) -> bool:
    return event.type == EventType.status and bool(event.data and event.data.get("terminal"))


def _final_message(status: RunStatus) -> str:
    return {
        RunStatus.completed: "Run completed",
        RunStatus.partial: "Run finished with a partial answer",
        RunStatus.insufficient_evidence: "Run finished: not enough evidence for an answer",
        RunStatus.failed: "Run failed",
        RunStatus.cancelled: "Run cancelled",
        RunStatus.interrupted: "Run interrupted",
    }.get(status, f"Run {status.value}")


async def wait_for(manager: RunManager, run_id: str) -> None:
    """Test/CLI helper: wait until a run's task finishes."""
    active = manager._active.get(run_id)
    if active and active.task:
        with contextlib.suppress(asyncio.CancelledError):
            await active.task
