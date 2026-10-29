from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import Any

import pytest

from predixion.config import Settings
from predixion.contracts import Mode, ResearchReport, ResearchRequest
from predixion.fixtures import FixtureExtract, FixtureModel, FixtureSearch, Scenario, load_scenarios
from predixion.llm import ModelOutcome
from predixion.orchestrator import Providers, ResearchRun
from predixion.prompts import TaskSpec
from predixion.tools import SearchOutcome

TODAY = date(2026, 10, 28)
RUN_ID = "run_" + "0" * 24

_PROVIDER_ENV = (
    "OPENAI_API_KEY",
    "TAVILY_API_KEY",
    "GROQ_API_KEY",
    "GROQ_TASKS",
    "MODEL_FALLBACK",
    "PREDIXION_MODE",
    "PREDIXION_ENV",
    "AUTH_MODE",
    "API_TOKEN_HASHES",
    "PUBLIC_ACCESS",
    "LIVE_RUNS_PER_USER_PER_HOUR",
    "LIVE_RUNS_PER_DAY",
    "LIVE_LEDGER_PATH",
    "HSTS_MAX_AGE_S",
    "ENABLE_FAULT_INJECTION",
    "SERVE_FRONTEND_DIR",
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("PREDIXION_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="live provider test; set PREDIXION_LIVE_TESTS=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_provider_env(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Unit tests never see real credentials or the developer's mode settings."""
    if "live" in request.keywords:
        return
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"PREDIXION_MODE": "fixture", "PREDIXION_DB_PATH": ":memory:", "LOG_LEVEL": "WARNING"}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def settings() -> Settings:
    return make_settings(ENABLE_FAULT_INJECTION=True)


def scenario(scenario_id: str) -> Scenario:
    return load_scenarios()[scenario_id]


class EventLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None, str, dict | None]] = []

    def __call__(self, type_, stage, message, data) -> None:
        self.events.append((type_.value, stage.value if stage else None, message, data))

    def messages(self, type_: str) -> list[str]:
        return [m for t, _, m, _ in self.events if t == type_]


def fixture_providers(sc: Scenario | None, *, model: Any = None, mode: Mode = Mode.fixture) -> Providers:
    return Providers(FixtureSearch(sc), FixtureExtract(sc), model or FixtureModel(sc), mode)


async def run_research(
    question: str,
    settings: Settings,
    providers: Providers,
    *,
    events: EventLog | None = None,
    **request: Any,
) -> ResearchReport:
    run = ResearchRun(
        RUN_ID, ResearchRequest(question=question, **request), settings, providers, events or EventLog(), today=TODAY
    )
    return await run.execute()


async def run_scenario(scenario_id: str, settings: Settings, *, model: Any = None, **request: Any) -> ResearchReport:
    sc = scenario(scenario_id)
    return await run_research(sc.question, settings, fixture_providers(sc, model=model), **request)


class RecordingModel(FixtureModel):
    """Fixture model that keeps every prompt it was sent."""

    def __init__(self, sc: Scenario | None) -> None:
        super().__init__(sc)
        self.inputs: list[tuple[str, str]] = []

    async def generate(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, timeout: float) -> ModelOutcome:
        self.inputs.append((spec.task.value, input_text))
        return await super().generate(spec, input_text, payload, timeout=timeout)


class SlowSearch(FixtureSearch):
    """Search that blocks until cancelled, for cancellation and capacity tests."""

    def __init__(self, sc: Scenario | None, delay_s: float = 30.0) -> None:
        super().__init__(sc)
        self.delay_s = delay_s
        self.started = asyncio.Event()

    async def search(self, args, *, timeout: float) -> SearchOutcome:
        self.started.set()
        await asyncio.sleep(self.delay_s)
        return await super().search(args, timeout=timeout)
