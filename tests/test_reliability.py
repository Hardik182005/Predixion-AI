from __future__ import annotations

import random

import pytest

from predixion.reliability import (
    AttemptLog,
    Budget,
    BudgetExhausted,
    Deadline,
    DeadlineReached,
    ErrorKind,
    ProviderError,
    RetryPolicy,
    call_with_retries,
    classify_http_status,
    parse_retry_after,
)


@pytest.mark.parametrize(
    ("status", "kind", "retryable"),
    [
        (429, ErrorKind.rate_limited, True),
        (401, ErrorKind.auth, False),
        (403, ErrorKind.auth, False),
        (402, ErrorKind.quota, False),
        (432, ErrorKind.quota, False),
        (500, ErrorKind.server_error, True),
        (503, ErrorKind.server_error, True),
        (408, ErrorKind.server_error, True),
        (400, ErrorKind.bad_request, False),
        (422, ErrorKind.bad_request, False),
    ],
)
def test_http_status_classification(status: int, kind: ErrorKind, retryable: bool) -> None:
    error = classify_http_status("tavily", status, f"HTTP {status}", None)
    assert error.kind == kind
    assert error.retryable is retryable


def test_retry_after_parsing() -> None:
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after("-3") == 0.0
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert parse_retry_after(None) is None


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Sleeper:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self.delays: list[float] = []
        self.clock = clock

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if self.clock:
            self.clock.now += delay


def _flaky(errors: list[ProviderError], result: str = "ok"):
    calls = {"n": 0}

    async def op(timeout: float) -> str:
        calls["n"] += 1
        if errors:
            raise errors.pop(0)
        return result

    return op, calls


async def _call(op, *, deadline: Deadline | None = None, sleep: Sleeper | None = None, log: AttemptLog | None = None, **kw):
    return await call_with_retries(
        op,
        policy=RetryPolicy(max_attempts=kw.pop("max_attempts", 3)),
        deadline=deadline or Deadline(120, 20),
        preferred_timeout=10,
        sleep=sleep or Sleeper(),
        rng=random.Random(0),
        log=log,
        **kw,
    )


async def test_transient_errors_are_retried() -> None:
    op, calls = _flaky([classify_http_status("t", 503, "x", None), classify_http_status("t", 429, "x", 2.0)])
    sleep, log = Sleeper(), AttemptLog()
    assert await _call(op, sleep=sleep, log=log) == "ok"
    assert calls["n"] == 3
    assert log.retries == 2
    assert sleep.delays[1] == 2.0  # Retry-After honored
    assert 0 <= sleep.delays[0] <= 0.5  # first backoff with full jitter


async def test_retry_after_is_capped() -> None:
    op, _ = _flaky([classify_http_status("t", 429, "x", 3600.0)])
    sleep = Sleeper()
    await _call(op, sleep=sleep)
    assert sleep.delays == [20.0]


async def test_non_retryable_errors_fail_immediately() -> None:
    for status in (401, 402, 400):
        op, calls = _flaky([classify_http_status("t", status, "x", None)])
        with pytest.raises(ProviderError):
            await _call(op)
        assert calls["n"] == 1


async def test_attempts_are_bounded() -> None:
    op, calls = _flaky([classify_http_status("t", 500, "x", None) for _ in range(10)])
    log = AttemptLog()
    with pytest.raises(ProviderError) as info:
        await _call(op, log=log)
    assert info.value.kind == ErrorKind.server_error
    assert calls["n"] == 3
    assert log.errors == ["t:server_error"] * 3


async def test_timeouts_from_the_operation_are_retryable() -> None:
    attempts = {"n": 0}

    async def op(timeout: float) -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError
        return "ok"

    assert await _call(op) == "ok"
    assert attempts["n"] == 2


async def test_no_retry_sleep_past_the_deadline() -> None:
    clock = FakeClock()
    deadline = Deadline(30, 10, clock=clock)  # 20 s of research time
    clock.now = 12.0
    op, calls = _flaky([classify_http_status("t", 429, "x", 15.0)])
    sleep = Sleeper(clock)
    with pytest.raises(ProviderError):
        await _call(op, deadline=deadline, sleep=sleep)
    assert calls["n"] == 1
    assert sleep.delays == []


async def test_finalizing_calls_may_use_the_reserve() -> None:
    clock = FakeClock()
    deadline = Deadline(30, 10, clock=clock)
    clock.now = 22.0  # research time is gone, reserve remains
    with pytest.raises(DeadlineReached):
        deadline.op_timeout(10)
    assert deadline.op_timeout(10, finalizing=True) == 7.0
    op, _ = _flaky([])
    assert await _call(op, deadline=deadline, finalizing=True) == "ok"


async def test_budget_check_runs_before_each_attempt() -> None:
    budget = Budget(3, 1_000_000, 10.0, 8, 1.0, 5.0, 0.0)

    def reserve() -> None:
        budget.reserve_model_attempt(100, 100)

    op, calls = _flaky([classify_http_status("t", 500, "x", None) for _ in range(10)])
    with pytest.raises(BudgetExhausted):
        await _call(op, before_attempt=reserve, max_attempts=5)
    assert calls["n"] == 3
    assert budget.model_attempts == 3


# ---------------------------------------------------------------------------
# Budget


def _budget(**overrides) -> Budget:
    values = {
        "max_model_attempts": 4,
        "max_tokens": 10_000,
        "max_cost_usd": 0.05,
        "max_pages": 5,
        "input_usd_per_mtok": 1.0,
        "output_usd_per_mtok": 5.0,
        "usd_per_credit": 0.008,
    }
    values.update(overrides)
    return Budget(**values)


def test_budget_limits() -> None:
    with pytest.raises(BudgetExhausted) as info:
        _budget(max_tokens=1_000).reserve_model_attempt(800, 400)
    assert info.value.resource == "tokens"

    with pytest.raises(BudgetExhausted) as info:
        _budget(max_cost_usd=0.001).reserve_model_attempt(500, 500)
    assert info.value.resource == "cost"

    budget = _budget(max_model_attempts=1)
    budget.reserve_model_attempt(10, 10)
    with pytest.raises(BudgetExhausted) as info:
        budget.reserve_model_attempt(10, 10)
    assert info.value.resource == "model_attempts"


def test_settle_with_reported_usage_releases_the_reservation() -> None:
    budget = _budget()
    res = budget.reserve_model_attempt(1_000, 2_000)
    assert budget.tokens_reserved == 3_000
    budget.settle_model(res, 900, 100)
    budget.settle_model(res, 900, 100)  # idempotent
    assert budget.tokens_reserved == 0
    assert budget.tokens_committed == 1_000
    assert budget.spent_usd == pytest.approx((900 * 1 + 100 * 5) / 1e6)
    assert not budget.cost_uncertain


def test_settle_with_unknown_usage_keeps_the_worst_case() -> None:
    budget = _budget()
    res = budget.reserve_model_attempt(1_000, 2_000)
    budget.settle_model(res, None, None)
    assert budget.tokens_committed == 3_000
    assert budget.spent_usd == pytest.approx((1_000 * 1 + 2_000 * 5) / 1e6)
    assert budget.cost_uncertain


def test_page_budget_and_credits() -> None:
    budget = _budget()
    assert budget.reserve_pages(3) == 3
    assert budget.reserve_pages(3) == 2
    assert budget.reserve_pages(1) == 0
    budget.release_pages(2)
    assert budget.reserve_pages(5) == 2
    budget.charge_credits(2)
    assert budget.spent_usd == pytest.approx(0.016)
    assert not budget.can_spend_credits(5)
