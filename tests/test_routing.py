"""Model routes and cross-provider fallback in ModelCaller. No network access."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from predixion.contracts import ExecutionMetrics
from predixion.fixtures import FixtureModel
from predixion.llm import FaultyModel, ModelCaller, ModelOption, ModelOutcome, ModelRoutes, live_routes
from predixion.logs import redact
from predixion.prompts import Task, TaskSpec, spec
from predixion.reliability import Budget, Deadline, ErrorKind, ModelPrice, ProviderError, RetryPolicy, classify_http_status

from .conftest import fixture_providers, make_settings, run_research, scenario

PLAN = spec(Task.plan, today="2026-10-28")
GROQ_BIG = ModelPrice(0.15, 0.60)
GROQ_SMALL = ModelPrice(0.075, 0.30)


class Scripted:
    """Replays scripted results in order (a ProviderError is raised), then succeeds."""

    sdk_version = None

    def __init__(self, model: str, *results: ProviderError) -> None:
        self.model = model
        self.results = list(results)
        self.calls = 0

    async def generate(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, timeout: float) -> ModelOutcome:
        self.calls += 1
        if self.results:
            raise self.results.pop(0)
        return ModelOutcome({"model": self.model}, 1_000, 100)


def http(status: int, provider: str = "groq") -> ProviderError:
    return classify_http_status(provider, status, f"HTTP {status}", None)


class Models:
    def __init__(self) -> None:
        self.openai = Scripted("gpt-test")
        self.big = Scripted("openai/gpt-oss-120b")
        self.small = Scripted("openai/gpt-oss-20b")

    def routes(self, *, groq_tasks: tuple[str, ...] = ("plan",), max_request: int = 8_000, fallback: bool = True) -> ModelRoutes:
        openai = ModelOption("openai", self.openai)
        big = ModelOption("groq", self.big, GROQ_BIG, max_request)
        small = ModelOption("groq", self.small, GROQ_SMALL, max_request)
        return ModelRoutes(default=(openai, big, small), by_task={t: (big, small, openai) for t in groq_tasks}, fallback=fallback)


def caller(routes: ModelRoutes, *, max_cost_usd: float = 10.0) -> ModelCaller:
    budget = Budget(
        max_model_attempts=8,
        max_tokens=1_000_000,
        max_cost_usd=max_cost_usd,
        max_pages=8,
        input_usd_per_mtok=1.0,
        output_usd_per_mtok=5.0,
        usd_per_credit=0.0,
    )
    return ModelCaller(
        routes,
        budget=budget,
        deadline=Deadline(120, 20),
        metrics=ExecutionMetrics(started_at=datetime.now(UTC)),
        policy=RetryPolicy(max_attempts=3, base_delay_s=0.0),
        timeout_s=10,
    )


async def test_groq_tasks_run_on_groq_at_groq_prices() -> None:
    m = Models()
    c = caller(m.routes())
    assert await c.call(PLAN, "question", {}) == {"model": "openai/gpt-oss-120b"}
    assert (m.big.calls, m.openai.calls) == (1, 0)
    assert c.metrics.models_used == {"groq:openai/gpt-oss-120b": 1}
    assert c.budget.spent_usd == pytest.approx(GROQ_BIG.cost(1_000, 100))


async def test_other_tasks_run_on_openai_at_the_default_prices() -> None:
    m = Models()
    c = caller(m.routes(groq_tasks=()))
    assert await c.call(PLAN, "question", {}) == {"model": "gpt-test"}
    assert (m.openai.calls, m.big.calls) == (1, 0)
    assert c.budget.spent_usd == pytest.approx((1_000 * 1.0 + 100 * 5.0) / 1e6)


async def test_rate_limits_fall_back_without_retrying_the_same_model() -> None:
    m = Models()
    m.big.results = [http(429)]
    m.small.results = [http(429)]
    c = caller(m.routes())
    assert await c.call(PLAN, "question", {}) == {"model": "gpt-test"}
    assert (m.big.calls, m.small.calls, m.openai.calls) == (1, 1, 1)
    assert (c.metrics.model_fallbacks, c.metrics.model_attempts, c.metrics.retries) == (2, 3, 0)
    assert c.metrics.models_used == {"openai:gpt-test": 1}
    # The rejected requests were not billed.
    assert c.budget.spent_usd == pytest.approx((1_000 * 1.0 + 100 * 5.0) / 1e6)


async def test_the_last_model_keeps_normal_retries() -> None:
    m = Models()
    m.big.results = [http(503)]
    m.small.results = [http(503)]
    m.openai.results = [http(503, "openai")]
    c = caller(m.routes())
    assert await c.call(PLAN, "question", {}) == {"model": "gpt-test"}
    assert (m.big.calls, m.small.calls, m.openai.calls) == (1, 1, 2)
    assert c.metrics.retries == 1


async def test_requests_too_large_for_groq_go_to_openai() -> None:
    m = Models()
    c = caller(m.routes(max_request=1_000))
    assert await c.call(PLAN, "question", {}) == {"model": "gpt-test"}
    assert (m.big.calls, m.small.calls, m.openai.calls) == (0, 0, 1)
    assert c.metrics.model_fallbacks == 0


async def test_an_auth_error_skips_that_provider_for_the_rest_of_the_run() -> None:
    m = Models()
    m.big.results = [http(401)]
    c = caller(m.routes())
    assert await c.call(PLAN, "question", {}) == {"model": "gpt-test"}
    assert await c.call(PLAN, "question", {}) == {"model": "gpt-test"}
    assert (m.big.calls, m.small.calls, m.openai.calls) == (1, 0, 2)


async def test_a_disabled_provider_with_no_alternative_raises_its_error() -> None:
    m = Models()
    m.openai.results = [ProviderError("openai", ErrorKind.quota, "HTTP 429 (insufficient_quota)", status_code=429)]
    c = caller(m.routes(groq_tasks=(), max_request=5_000))
    assert await c.call(PLAN, "question", {}) == {"model": "openai/gpt-oss-120b"}  # fits Groq, so it falls back
    big_task = spec(Task.synthesize, max_output_tokens=6_000)
    with pytest.raises(ProviderError) as info:
        await c.call(big_task, "question", {})  # too large for Groq, and OpenAI is out of quota
    assert (info.value.provider, info.value.kind) == ("openai", ErrorKind.quota)
    assert m.openai.calls == 1


async def test_a_refusal_is_not_sent_to_another_model() -> None:
    m = Models()
    m.big.results = [ProviderError("groq", ErrorKind.refusal, "model refused the request", retryable=False)]
    c = caller(m.routes())
    with pytest.raises(ProviderError) as info:
        await c.call(PLAN, "question", {})
    assert info.value.kind == ErrorKind.refusal
    assert (m.small.calls, m.openai.calls) == (0, 0)


async def test_with_fallback_off_only_the_first_model_that_fits_is_used() -> None:
    m = Models()
    m.big.results = [http(429), http(429), http(429)]
    c = caller(m.routes(fallback=False))
    with pytest.raises(ProviderError) as info:
        await c.call(PLAN, "question", {})
    assert info.value.kind == ErrorKind.rate_limited
    assert (m.big.calls, m.small.calls, m.openai.calls) == (3, 0, 0)

    m = Models()
    c = caller(m.routes(fallback=False, max_request=1_000))
    assert await c.call(PLAN, "question", {}) == {"model": "gpt-test"}


def test_can_afford_assumes_the_priciest_model_the_task_may_use() -> None:
    m = Models()
    # Enough for a worst-case Groq attempt, not for a worst-case OpenAI one.
    cap = 0.004
    assert caller(m.routes(), max_cost_usd=cap).can_afford(PLAN, "question") is False
    assert caller(m.routes(fallback=False), max_cost_usd=cap).can_afford(PLAN, "question") is True


async def test_injected_faults_apply_to_every_model() -> None:
    m = Models()
    routes = m.routes().wrap(lambda client: FaultyModel(client, "unavailable"))
    c = caller(routes)
    with pytest.raises(ProviderError) as info:
        await c.call(PLAN, "question", {})
    assert info.value.kind == ErrorKind.server_error
    assert c.metrics.model_attempts == 5  # one each on the Groq models, then three on the last model
    assert m.openai.calls == m.big.calls == 0


async def test_a_run_reports_fallbacks_and_the_models_used(settings) -> None:
    sc = scenario("vector_databases")
    fixture = FixtureModel(sc)
    limited = Scripted("gpt-oss-test", http(429))
    primary = ModelOption("fixture", fixture)
    groq = ModelOption("groq", limited)
    providers = fixture_providers(sc, model=fixture)
    providers.routes = ModelRoutes(default=(primary,), by_task={"plan": (groq, primary)})
    report = await run_research(sc.question, settings, providers)
    m = report.execution.metrics
    assert report.status.value == "completed"
    assert m.model_fallbacks == 1
    assert m.models_used == {"fixture:fixture-heuristic-v1": m.model_calls}
    assert report.execution.model == "fixture-heuristic-v1"


# ---------------------------------------------------------------------------
# Settings


LIVE = {"OPENAI_API_KEY": "sk-test-openai-key", "TAVILY_API_KEY": "tvly-test-key"}
GROQ_KEY = "gsk_testsecretkey123"


async def test_live_routes_put_groq_first_only_for_groq_tasks() -> None:
    settings = make_settings(**LIVE, GROQ_API_KEY=GROQ_KEY, GROQ_TASKS="plan, verify")
    routes, clients = live_routes(settings)
    try:
        labels = {task: [o.label for o in routes.options(task)] for task in ("plan", "verify", "synthesize")}
        groq = ["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b"]
        assert labels["plan"] == labels["verify"] == [*groq, "openai:gpt-6.1-terra"]
        assert labels["synthesize"] == ["openai:gpt-6.1-terra", *groq]
        assert routes.primary.model == "gpt-6.1-terra"
        assert [o.price for o in routes.options("plan")] == [GROQ_BIG, GROQ_SMALL, None]
        assert {o.max_request_tokens for o in routes.options("plan") if o.provider == "groq"} == {8_000}
    finally:
        for client in clients:
            await client.aclose()


async def test_live_routes_without_groq_use_openai_only() -> None:
    routes, clients = live_routes(make_settings(**LIVE))
    try:
        assert [o.label for o in routes.options("plan")] == ["openai:gpt-6.1-terra"]
        assert len(clients) == 1
    finally:
        for client in clients:
            await client.aclose()

    routes, clients = live_routes(make_settings(**LIVE, GROQ_API_KEY=GROQ_KEY, GROQ_FALLBACK_MODEL=""))
    try:
        assert [o.label for o in routes.options("plan")] == ["groq:openai/gpt-oss-120b", "openai:gpt-6.1-terra"]
    finally:
        for client in clients:
            await client.aclose()


def test_unknown_groq_tasks_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(GROQ_TASKS="plan,summarize")
    assert make_settings(GROQ_TASKS="").groq_task_list == []


def test_groq_keys_are_redacted_from_logs() -> None:
    assert "gsk_" not in redact('{"msg": "failed", "detail": "key gsk_abcdefghijklmnop1234"}')
