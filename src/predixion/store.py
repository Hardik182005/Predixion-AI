"""SQLite persistence for runs, events, and reports.

One connection guarded by a lock; writes are small and short. Every read that
returns run data is scoped to an owner. Runs older than the retention window
are deleted, and runs that were active when the process stopped are marked
interrupted on the next start.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .contracts import (
    TERMINAL_STATUSES,
    EventType,
    Mode,
    ResearchPlan,
    ResearchReport,
    RunEvent,
    RunStatus,
    RunSummary,
    RunView,
    StopReason,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    question TEXT NOT NULL,
    mode TEXT NOT NULL,
    idempotency_key TEXT,
    request_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    stop_reason TEXT,
    error TEXT,
    plan_json TEXT,
    report_json TEXT,
    last_event_seq INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS runs_idempotency ON runs(owner, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS runs_owner_created ON runs(owner, created_at DESC);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    stage TEXT,
    message TEXT NOT NULL,
    data_json TEXT,
    PRIMARY KEY (run_id, seq)
);
"""

ACTIVE = (RunStatus.queued.value, RunStatus.running.value)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def ping(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1").fetchone() is not None

    # -- runs ------------------------------------------------------------

    def create_run(
        self, *, run_id: str, owner: str, question: str, mode: Mode, idempotency_key: str | None, request_hash: str
    ) -> RunSummary:
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (run_id, owner, status, question, mode, idempotency_key, request_hash, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, owner, RunStatus.queued.value, question, mode.value, idempotency_key, request_hash, now, now),
            )
        return RunSummary(
            run_id=run_id,
            status=RunStatus.queued,
            question=question,
            mode=mode,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    def find_idempotent(self, owner: str, key: str) -> tuple[str, str, RunStatus] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id, request_hash, status FROM runs WHERE owner = ? AND idempotency_key = ?", (owner, key)
            ).fetchone()
        return (row["run_id"], row["request_hash"], RunStatus(row["status"])) if row else None

    def set_status(
        self, run_id: str, status: RunStatus, *, stop_reason: StopReason | None = None, error: str | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET status = ?, stop_reason = COALESCE(?, stop_reason), error = COALESCE(?, error), updated_at = ?"
                " WHERE run_id = ?",
                (status.value, stop_reason.value if stop_reason else None, error, _now(), run_id),
            )

    def save_plan(self, run_id: str, plan: ResearchPlan) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET plan_json = ?, updated_at = ? WHERE run_id = ?", (plan.model_dump_json(), _now(), run_id)
            )

    def save_report(self, run_id: str, report: ResearchReport) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET report_json = ?, plan_json = COALESCE(?, plan_json), status = ?, stop_reason = ?,"
                " updated_at = ? WHERE run_id = ?",
                (
                    report.model_dump_json(),
                    report.plan.model_dump_json() if report.plan else None,
                    report.status.value,
                    report.stop_reason.value if report.stop_reason else None,
                    _now(),
                    run_id,
                ),
            )

    def get_run(self, run_id: str, owner: str) -> RunView | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE run_id = ? AND owner = ?", (run_id, owner)).fetchone()
        return _view(row) if row else None

    def get_status(self, run_id: str, owner: str) -> RunStatus | None:
        with self._lock:
            row = self._conn.execute("SELECT status FROM runs WHERE run_id = ? AND owner = ?", (run_id, owner)).fetchone()
        return RunStatus(row["status"]) if row else None

    def list_runs(self, owner: str, limit: int = 20) -> list[RunSummary]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, status, question, mode, created_at, updated_at, stop_reason FROM runs"
                " WHERE owner = ? ORDER BY created_at DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
        return [_summary(r) for r in rows]

    def delete_run(self, run_id: str, owner: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM runs WHERE run_id = ? AND owner = ?", (run_id, owner))
        return cur.rowcount > 0

    # -- events ----------------------------------------------------------

    def append_event(self, run_id: str, event: RunEvent) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO events (run_id, seq, ts, type, stage, message, data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    event.seq,
                    event.ts.isoformat(),
                    event.type.value,
                    event.stage.value if event.stage else None,
                    event.message,
                    json.dumps(event.data, default=str) if event.data is not None else None,
                ),
            )
            self._conn.execute("UPDATE runs SET last_event_seq = MAX(last_event_seq, ?) WHERE run_id = ?", (event.seq, run_id))

    def events_after(self, run_id: str, after_seq: int) -> list[RunEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, ts, type, stage, message, data_json FROM events WHERE run_id = ? AND seq > ? ORDER BY seq",
                (run_id, after_seq),
            ).fetchall()
        return [
            RunEvent(
                seq=r["seq"],
                ts=datetime.fromisoformat(r["ts"]),
                type=r["type"],
                stage=r["stage"],
                message=r["message"],
                data=json.loads(r["data_json"]) if r["data_json"] else None,
            )
            for r in rows
        ]

    # -- maintenance -----------------------------------------------------

    def mark_interrupted(self) -> list[str]:
        """Runs left active by a previous process. They cannot resume, so they end as interrupted.

        Each also gets a terminal status event, so a client that reconnects to the
        event stream learns the run is over instead of waiting for events that never come.
        """
        with self._lock:
            rows = self._conn.execute(
                f"SELECT run_id, last_event_seq FROM runs WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE
            ).fetchall()
            ids = [r["run_id"] for r in rows]
            if ids:
                self._conn.execute(
                    f"UPDATE runs SET status = ?, stop_reason = ?, error = ?, updated_at = ? WHERE status IN ({','.join('?' * len(ACTIVE))})",
                    (
                        RunStatus.interrupted.value,
                        StopReason.process_interrupted.value,
                        "The server stopped while this run was active.",
                        _now(),
                        *ACTIVE,
                    ),
                )
        for row in rows:
            data = {"status": RunStatus.interrupted.value, "stop_reason": StopReason.process_interrupted.value, "terminal": True}
            event = RunEvent(
                seq=row["last_event_seq"] + 1, ts=datetime.now(UTC), type=EventType.status, message="Run interrupted", data=data
            )
            self.append_event(row["run_id"], event)
        return ids

    def purge_expired(self, retention_days: float) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        terminal = tuple(s.value for s in TERMINAL_STATUSES)
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM runs WHERE updated_at < ? AND status IN ({','.join('?' * len(terminal))})", (cutoff, *terminal)
            )
        return cur.rowcount


def _summary(row: sqlite3.Row) -> RunSummary:
    return RunSummary(
        run_id=row["run_id"],
        status=RunStatus(row["status"]),
        question=row["question"],
        mode=Mode(row["mode"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        stop_reason=StopReason(row["stop_reason"]) if row["stop_reason"] else None,
    )


def _view(row: sqlite3.Row) -> RunView:
    s = _summary(row)
    return RunView(
        **s.model_dump(),
        report=ResearchReport.model_validate_json(row["report_json"]) if row["report_json"] else None,
        plan=ResearchPlan.model_validate_json(row["plan_json"]) if row["plan_json"] else None,
        last_event_seq=row["last_event_seq"],
        error=row["error"],
    )
