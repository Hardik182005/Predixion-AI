"""Errors, deadlines, budgets, and the single retry owner.

Every provider call in the workflow goes through `call_with_retries`. SDK-level
retries are disabled at client construction so attempts are counted exactly once.
Budget bookkeeping is synchronous (no awaits between check and update), so it is
atomic with respect to other coroutines on the same event loop.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar

T = TypeVar("T")


class ErrorKind(StrEnum):
    rate_limited = "rate_limited"
    server_error = "server_error"
    timeout = "timeout"
    connection = "connection"
    auth = "auth"
    quota = "quota"
    bad_request = "bad_request"
    malformed_response = "malformed_response"
    refusal = "refusal"
    incomplete = "incomplete"


RETRYABLE_KINDS = frozenset({ErrorKind.rate_limited, ErrorKind.server_error, ErrorKind.timeout, ErrorKind.connection})


class ProviderError(Exception):
    """A classified failure from an external provider. Messages are safe to log."""

    def __init__(
        self,
        provider: str,
        kind: ErrorKind,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        retryable: bool | None = None,
        usage: tuple[int, int] | None = None,
    ) -> None:
        super().__init__(f"{provider}: {kind}: {message}")
        self.provider = provider
        self.kind = kind
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after
        self.retryable = kind in RETRYABLE_KINDS if retryable is None else retryable
        # Token usage reported with a failed model response (e.g. incomplete), if any.
        self.usage = usage


class BudgetExhausted(Exception):
    def __init__(self, resource: str) -> None:
        super().__init__(f"budget exhausted: {resource}")
        self.resource = resource


class DeadlineReached(Exception):
    pass


def classify_http_status(provider: str, status: int, message: str, retry_after: float | None):
    if status == 429:
        return ProviderError(provider, ErrorKind.rate_limited, message, status_code=status, retry_after=retry_after)
    if status in (401, 403):
        return ProviderError(provider, ErrorKind.auth, message, status_code=status)
    if status in (402, 432, 433):
        return ProviderError(provider, ErrorKind.quota, message, status_code=status)
    if status in (408, 409) or status >= 500:
        return ProviderError(provider, ErrorKind.server_error, message, status_code=status, retry_after=retry_after)
    return ProviderError(provider, ErrorKind.bad_request, message, status_code=status)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date form is ignored; backoff applies instead


class Deadline:
    """Global wall-clock deadline with a reserve for verification and finalization."""

    def __init__(self, total_s: float, reserve_s: float, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.start = clock()
        self.total_s = total_s
        self.reserve_s = min(reserve_s, total_s * 0.5)

    def elapsed(self) -> float:
        return self._clock() - self.start

    def remaining(self) -> float:
        return self.total_s - self.elapsed()

    def research_remaining(self) -> float:
        """Time left for research stages before the finalization reserve begins."""
        return self.remaining() - self.reserve_s

    def op_timeout(self, preferred: float, *, finalizing: bool = False) -> float:
        """Per-operation timeout bounded by the time actually left."""
        left = self.remaining() - 1.0 if finalizing else self.research_remaining()
        if left <= 0.5:
            raise DeadlineReached()
        return max(0.5, min(preferred, left))


@dataclass
class Reservation:
    tokens: int
    cost_usd: float
    settled: bool = False


@dataclass
class Budget:
    """Per-run budget shared by retries, follow-up research, and repair."""

    max_model_attempts: int
    max_tokens: int
    max_cost_usd: float
    max_pages: int
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    usd_per_credit: float
    model_attempts: int = 0
    tokens_committed: int = 0
    tokens_reserved: int = 0
    cost_committed: float = 0.0
    cost_reserved: float = 0.0
    pages_reserved: int = 0
    cost_uncertain: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    credits: float = 0.0
    _events: list[str] = field(default_factory=list)

    def model_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok) / 1_000_000

    def attempts_left(self) -> int:
        return self.max_model_attempts - self.model_attempts

    def reserve_model_attempt(self, est_input_tokens: int, max_output_tokens: int) -> Reservation:
        """Reserve the worst case for one model attempt before sending it."""
        if self.model_attempts >= self.max_model_attempts:
            raise BudgetExhausted("model_attempts")
        tokens = est_input_tokens + max_output_tokens
        cost = self.model_cost(est_input_tokens, max_output_tokens)
        if self.tokens_committed + self.tokens_reserved + tokens > self.max_tokens:
            raise BudgetExhausted("tokens")
        if self.cost_committed + self.cost_reserved + cost > self.max_cost_usd:
            raise BudgetExhausted("cost")
        self.model_attempts += 1
        self.tokens_reserved += tokens
        self.cost_reserved += cost
        return Reservation(tokens=tokens, cost_usd=cost)

    def settle_model(self, res: Reservation, input_tokens: int | None, output_tokens: int | None) -> None:
        """Reconcile a reservation. Unknown usage (e.g. timeout) keeps the full reservation as spent."""
        if res.settled:
            return
        res.settled = True
        self.tokens_reserved -= res.tokens
        self.cost_reserved -= res.cost_usd
        if input_tokens is None or output_tokens is None:
            self.tokens_committed += res.tokens
            self.cost_committed += res.cost_usd
            self.cost_uncertain = True
            return
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.tokens_committed += input_tokens + output_tokens
        self.cost_committed += self.model_cost(input_tokens, output_tokens)

    def charge_credits(self, credits: float) -> None:
        self.credits += credits
        self.cost_committed += credits * self.usd_per_credit

    def can_spend_credits(self, credits: float) -> bool:
        return self.cost_committed + self.cost_reserved + credits * self.usd_per_credit <= self.max_cost_usd

    def reserve_pages(self, wanted: int) -> int:
        granted = max(0, min(wanted, self.max_pages - self.pages_reserved))
        self.pages_reserved += granted
        return granted

    def release_pages(self, count: int) -> None:
        self.pages_reserved = max(0, self.pages_reserved - count)

    @property
    def spent_usd(self) -> float:
        return self.cost_committed


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    max_retry_after_s: float = 20.0


@dataclass
class AttemptLog:
    attempts: int = 0
    retries: int = 0
    errors: list[str] = field(default_factory=list)


async def call_with_retries(
    op: Callable[[float], Awaitable[T]],
    *,
    policy: RetryPolicy,
    deadline: Deadline,
    preferred_timeout: float,
    finalizing: bool = False,
    before_attempt: Callable[[], object] | None = None,
    log: AttemptLog | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: random.Random | None = None,
) -> T:
    """Run `op(timeout)` with bounded retries for transient failures.

    - Retries only ProviderError with retryable=True.
    - Honors Retry-After (capped), otherwise exponential backoff with full jitter.
    - Never sleeps past the deadline; `before_attempt` may raise BudgetExhausted.
    """
    log = log or AttemptLog()
    rng = rng or random.Random()
    attempt = 0
    while True:
        attempt += 1
        timeout = deadline.op_timeout(preferred_timeout, finalizing=finalizing)
        if before_attempt is not None:
            before_attempt()
        log.attempts += 1
        try:
            return await asyncio.wait_for(op(timeout), timeout=timeout + 2.0)
        except TimeoutError as exc:
            error: ProviderError = ProviderError("runtime", ErrorKind.timeout, "operation timed out")
            error.__cause__ = exc
        except ProviderError as exc:
            error = exc
        log.errors.append(f"{error.provider}:{error.kind}")
        if not error.retryable or attempt >= policy.max_attempts:
            raise error
        if error.retry_after is not None:
            delay = min(error.retry_after, policy.max_retry_after_s)
        else:
            delay = rng.uniform(0, min(policy.max_delay_s, policy.base_delay_s * 2 ** (attempt - 1)))
        budget_left = deadline.remaining() - 1.0 if finalizing else deadline.research_remaining()
        if delay >= budget_left - 0.5:
            raise error
        log.retries += 1
        await sleep(delay)
