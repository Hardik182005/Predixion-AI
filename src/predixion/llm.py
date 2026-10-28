"""Model adapter (OpenAI Responses API) and the per-run model caller.

The SDK's own retries are disabled (`max_retries=0`); `call_with_retries` is
the only retry owner. Each attempt reserves its worst-case tokens and cost
before it is sent and is reconciled with reported usage afterwards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import openai
from openai import AsyncOpenAI

from .config import OPENAI_BASE_URL
from .contracts import ExecutionMetrics
from .prompts import TaskSpec, estimate_tokens
from .reliability import (
    AttemptLog,
    Budget,
    Deadline,
    ErrorKind,
    ProviderError,
    Reservation,
    RetryPolicy,
    call_with_retries,
    classify_http_status,
)


@dataclass
class ModelOutcome:
    data: dict[str, Any]
    input_tokens: int | None
    output_tokens: int | None


class ModelClient(Protocol):
    model: str
    sdk_version: str | None

    async def generate(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, timeout: float) -> ModelOutcome: ...


def _status_message(exc: openai.APIStatusError) -> str:
    code = None
    body = exc.body if isinstance(exc.body, dict) else None
    if body is not None:
        err = body.get("error", body)
        if isinstance(err, dict):
            code = err.get("code") or err.get("type")
    return f"HTTP {exc.status_code}" + (f" ({code})" if code else "")


class OpenAIModel:
    """Structured-output generation through the Responses API."""

    def __init__(self, api_key: str, model: str, reasoning_effort: str | None) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.sdk_version = openai.__version__
        self._client = AsyncOpenAI(api_key=api_key, base_url=OPENAI_BASE_URL, max_retries=0, timeout=60.0)

    async def aclose(self) -> None:
        await self._client.close()

    async def generate(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, timeout: float) -> ModelOutcome:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": spec.instructions,
            "input": input_text,
            "text": {"format": {"type": "json_schema", "name": spec.task.value, "schema": spec.schema, "strict": True}},
            "max_output_tokens": spec.max_output_tokens,
            "store": False,
            "timeout": timeout,
        }
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        try:
            response = await self._client.responses.create(**kwargs)
        except openai.APITimeoutError as exc:
            raise ProviderError("openai", ErrorKind.timeout, "request timed out") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("openai", ErrorKind.connection, "connection error") from exc
        except openai.APIStatusError as exc:
            message = _status_message(exc)
            if exc.status_code == 429 and "insufficient_quota" in message:
                raise ProviderError("openai", ErrorKind.quota, message, status_code=429) from exc
            retry_after = None
            try:
                retry_after = float(exc.response.headers.get("retry-after", ""))
            except (TypeError, ValueError):
                pass
            raise classify_http_status("openai", exc.status_code, message, retry_after) from exc

        usage = response.usage
        in_tok = usage.input_tokens if usage is not None else None
        out_tok = usage.output_tokens if usage is not None else None
        usage_pair = (in_tok, out_tok) if in_tok is not None and out_tok is not None else None

        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", None) or "unknown"
            raise ProviderError(
                "openai", ErrorKind.incomplete, f"incomplete response: {reason}", retryable=False, usage=usage_pair
            )
        for item in response.output or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise ProviderError(
                        "openai", ErrorKind.refusal, "model refused the request", retryable=False, usage=usage_pair
                    )
        try:
            data = json.loads(response.output_text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProviderError(
                "openai", ErrorKind.malformed_response, "output was not valid JSON", retryable=True, usage=usage_pair
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                "openai", ErrorKind.malformed_response, "output was not an object", retryable=True, usage=usage_pair
            )
        return ModelOutcome(data=data, input_tokens=in_tok, output_tokens=out_tok)


class FaultyModel:
    """Injected model failures for tests and demos."""

    def __init__(self, inner: ModelClient, mode: str) -> None:
        self.inner, self.mode = inner, mode
        self.model, self.sdk_version = inner.model, inner.sdk_version

    async def generate(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, timeout: float) -> ModelOutcome:
        if self.mode == "unavailable":
            raise ProviderError("model", ErrorKind.server_error, "injected: HTTP 503", status_code=503)
        if self.mode == "malformed":
            raise ProviderError(
                "model", ErrorKind.malformed_response, "injected: output was not valid JSON", retryable=True, usage=(100, 20)
            )
        if self.mode == "refusal":
            raise ProviderError(
                "model", ErrorKind.refusal, "injected: model refused the request", retryable=False, usage=(100, 5)
            )
        return await self.inner.generate(spec, input_text, payload, timeout=timeout)


class ModelCaller:
    """Runs model tasks for one run under its budget, deadline, and retry policy."""

    def __init__(
        self,
        client: ModelClient,
        *,
        budget: Budget,
        deadline: Deadline,
        metrics: ExecutionMetrics,
        policy: RetryPolicy,
        timeout_s: float,
    ) -> None:
        self.client = client
        self.budget = budget
        self.deadline = deadline
        self.metrics = metrics
        self.policy = policy
        self.timeout_s = timeout_s

    def can_afford(self, spec: TaskSpec, input_text: str, attempts: int = 1) -> bool:
        """Whether `attempts` more attempts of this task fit the remaining budget."""
        est = estimate_tokens(spec.instructions, input_text, json.dumps(spec.schema))
        b = self.budget
        if b.attempts_left() < attempts:
            return False
        tokens = (est + spec.max_output_tokens) * attempts
        cost = b.model_cost(est, spec.max_output_tokens) * attempts
        return (
            b.tokens_committed + b.tokens_reserved + tokens <= b.max_tokens
            and b.cost_committed + b.cost_reserved + cost <= b.max_cost_usd
        )

    async def call(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, finalizing: bool = False) -> dict[str, Any]:
        est = estimate_tokens(spec.instructions, input_text, json.dumps(spec.schema))
        pending: list[Reservation] = []

        def reserve() -> None:
            pending.append(self.budget.reserve_model_attempt(est, spec.max_output_tokens))

        async def attempt(timeout: float) -> dict[str, Any]:
            res = pending[-1]
            try:
                outcome = await self.client.generate(spec, input_text, payload, timeout=timeout)
            except ProviderError as exc:
                if exc.usage is not None:
                    self.budget.settle_model(res, *exc.usage)
                elif exc.status_code is not None and 400 <= exc.status_code < 500 and exc.status_code != 408:
                    self.budget.settle_model(res, 0, 0)  # rejected before generation; nothing billed
                else:
                    self.budget.settle_model(res, None, None)  # unknown: keep the full reservation
                raise
            except BaseException:
                self.budget.settle_model(res, None, None)
                raise
            finally:
                self.metrics.model_attempts += 1
            self.budget.settle_model(res, outcome.input_tokens, outcome.output_tokens)
            return outcome.data

        log = AttemptLog()
        self.metrics.model_calls += 1
        try:
            return await call_with_retries(
                attempt,
                policy=self.policy,
                deadline=self.deadline,
                preferred_timeout=self.timeout_s,
                finalizing=finalizing,
                before_attempt=reserve,
                log=log,
            )
        finally:
            for res in pending:
                # A wait_for timeout cancels the attempt before it settles.
                self.budget.settle_model(res, None, None)
            self.metrics.retries += log.retries
            self.metrics.input_tokens = self.budget.input_tokens
            self.metrics.output_tokens = self.budget.output_tokens
            self.metrics.cost_uncertain = self.budget.cost_uncertain
