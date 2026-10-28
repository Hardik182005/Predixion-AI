"""Model adapters (OpenAI Responses API, Groq Chat Completions), model routes, and the per-run model caller.

The SDK's own retries are disabled (`max_retries=0`); `call_with_retries` is
the only retry owner. Each attempt reserves its worst-case tokens and cost
before it is sent and is reconciled with reported usage afterwards.

Each task has an ordered list of models (`ModelRoutes`). The caller uses the
first one that fits the request and falls back to the next when a model fails.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

import openai
from openai import AsyncOpenAI

from .config import GROQ_BASE_URL, OPENAI_BASE_URL, Settings
from .contracts import ExecutionMetrics
from .logs import log
from .prompts import TaskSpec, estimate_tokens
from .reliability import (
    AttemptLog,
    Budget,
    Deadline,
    ErrorKind,
    ModelPrice,
    ProviderError,
    Reservation,
    RetryPolicy,
    call_with_retries,
    classify_http_status,
    parse_retry_after,
)

logger = logging.getLogger("predixion.llm")

# A refusal is about the request, not the model, so another model is not asked.
NO_FALLBACK_KINDS = frozenset({ErrorKind.refusal})
# A bad key or exhausted quota will not recover during a run, so the provider is skipped for the rest of it.
DISABLING_KINDS = frozenset({ErrorKind.auth, ErrorKind.quota})


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


def _usage_pair(input_tokens: int | None, output_tokens: int | None) -> tuple[int, int] | None:
    return (input_tokens, output_tokens) if input_tokens is not None and output_tokens is not None else None


def _parse_object(provider: str, text: str | None, usage: tuple[int, int] | None) -> dict[str, Any]:
    try:
        data = json.loads(text or "")
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProviderError(
            provider, ErrorKind.malformed_response, "output was not valid JSON", retryable=True, usage=usage
        ) from exc
    if not isinstance(data, dict):
        raise ProviderError(provider, ErrorKind.malformed_response, "output was not an object", retryable=True, usage=usage)
    return data


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
            retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
            raise classify_http_status("openai", exc.status_code, message, retry_after) from exc

        usage = response.usage
        in_tok = usage.input_tokens if usage is not None else None
        out_tok = usage.output_tokens if usage is not None else None
        usage_pair = _usage_pair(in_tok, out_tok)

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
        data = _parse_object("openai", response.output_text, usage_pair)
        return ModelOutcome(data=data, input_tokens=in_tok, output_tokens=out_tok)


# Groq accepts low, medium, and high for gpt-oss models.
GROQ_REASONING_EFFORT = {"none": "low", "minimal": "low", "low": "low", "medium": "medium", "high": "high"}


class GroqModel:
    """Structured-output generation through Groq's OpenAI-compatible Chat Completions API."""

    def __init__(self, api_key: str, model: str, reasoning_effort: str | None) -> None:
        self.model = model
        self.reasoning_effort = GROQ_REASONING_EFFORT.get(reasoning_effort) if reasoning_effort else None
        self.sdk_version = openai.__version__
        self._client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL, max_retries=0, timeout=60.0)

    async def aclose(self) -> None:
        await self._client.close()

    async def generate(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, timeout: float) -> ModelOutcome:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": spec.instructions}, {"role": "user", "content": input_text}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": spec.task.value, "schema": spec.schema, "strict": True},
            },
            "max_completion_tokens": spec.max_output_tokens,
            # Only the JSON answer is used, so the reasoning text is not returned.
            "extra_body": {"include_reasoning": False},
            "timeout": timeout,
        }
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:
            raise ProviderError("groq", ErrorKind.timeout, "request timed out") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("groq", ErrorKind.connection, "connection error") from exc
        except openai.APIStatusError as exc:
            message = _status_message(exc)
            retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
            if exc.status_code == 498:  # Groq: capacity exceeded
                raise ProviderError("groq", ErrorKind.rate_limited, message, status_code=498, retry_after=retry_after) from exc
            raise classify_http_status("groq", exc.status_code, message, retry_after) from exc

        usage = response.usage
        in_tok = usage.prompt_tokens if usage is not None else None
        out_tok = usage.completion_tokens if usage is not None else None
        usage_pair = _usage_pair(in_tok, out_tok)

        if not response.choices:
            raise ProviderError("groq", ErrorKind.malformed_response, "response had no choices", retryable=True, usage=usage_pair)
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ProviderError("groq", ErrorKind.incomplete, "incomplete response: length", retryable=False, usage=usage_pair)
        if choice.finish_reason == "content_filter" or getattr(choice.message, "refusal", None):
            raise ProviderError("groq", ErrorKind.refusal, "model refused the request", retryable=False, usage=usage_pair)
        data = _parse_object("groq", choice.message.content, usage_pair)
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


# ---------------------------------------------------------------------------
# Routes


@dataclass(frozen=True)
class ModelOption:
    """A model a task can run on, with its prices and the largest request its provider accepts."""

    provider: str
    client: ModelClient
    price: ModelPrice | None = None  # None: the run budget's default model prices
    max_request_tokens: int | None = None

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.client.model}"

    def fits(self, est_input_tokens: int, max_output_tokens: int) -> bool:
        return self.max_request_tokens is None or est_input_tokens + max_output_tokens <= self.max_request_tokens


@dataclass(frozen=True)
class ModelRoutes:
    """The models each task tries, in order. The first that fits the request is preferred; the rest are fallbacks."""

    default: tuple[ModelOption, ...]
    by_task: dict[str, tuple[ModelOption, ...]] = field(default_factory=dict)
    fallback: bool = True

    @classmethod
    def single(cls, client: ModelClient, provider: str) -> ModelRoutes:
        return cls(default=(ModelOption(provider, client),))

    @property
    def primary(self) -> ModelClient:
        return self.default[0].client

    def options(self, task: str) -> tuple[ModelOption, ...]:
        return self.by_task.get(task, self.default)

    def wrap(self, fn: Callable[[ModelClient], ModelClient]) -> ModelRoutes:
        """The same routes with every client wrapped, e.g. for fault injection."""

        def wrap_all(options: tuple[ModelOption, ...]) -> tuple[ModelOption, ...]:
            return tuple(replace(o, client=fn(o.client)) for o in options)

        return ModelRoutes(wrap_all(self.default), {t: wrap_all(o) for t, o in self.by_task.items()}, self.fallback)


def live_routes(settings: Settings) -> tuple[ModelRoutes, list[OpenAIModel | GroqModel]]:
    """Live model routes and the clients to close when done.

    Tasks in GROQ_TASKS try Groq's models first, then OpenAI. Other tasks try
    OpenAI first, then Groq. Groq is skipped for requests larger than
    GROQ_MAX_REQUEST_TOKENS. Without a Groq key, every task uses OpenAI only.
    """
    assert settings.openai_api_key is not None
    primary = OpenAIModel(settings.openai_api_key.get_secret_value(), settings.research_model, settings.reasoning_effort)
    openai_option = ModelOption("openai", primary)  # priced by MODEL_*_USD_PER_MTOK through the run budget
    clients: list[OpenAIModel | GroqModel] = [primary]
    groq: list[ModelOption] = []
    if settings.groq_api_key is not None:
        key = settings.groq_api_key.get_secret_value()
        models = [(settings.groq_model, ModelPrice(settings.groq_input_usd_per_mtok, settings.groq_output_usd_per_mtok))]
        if settings.groq_fallback_model:
            price = ModelPrice(settings.groq_fallback_input_usd_per_mtok, settings.groq_fallback_output_usd_per_mtok)
            models.append((settings.groq_fallback_model, price))
        for model, price in models:
            client = GroqModel(key, model, settings.reasoning_effort)
            clients.append(client)
            groq.append(ModelOption("groq", client, price, settings.groq_max_request_tokens))
    groq_first = (*groq, openai_option)
    routes = ModelRoutes(
        default=(openai_option, *groq),
        by_task={task: groq_first for task in settings.groq_task_list} if groq else {},
        fallback=settings.model_fallback,
    )
    return routes, clients


# ---------------------------------------------------------------------------
# Caller


class ModelCaller:
    """Runs model tasks for one run under its budget, deadline, and retry policy."""

    def __init__(
        self,
        routes: ModelRoutes,
        *,
        budget: Budget,
        deadline: Deadline,
        metrics: ExecutionMetrics,
        policy: RetryPolicy,
        timeout_s: float,
    ) -> None:
        self.routes = routes
        self.budget = budget
        self.deadline = deadline
        self.metrics = metrics
        self.policy = policy
        self.timeout_s = timeout_s
        self._disabled: dict[str, ProviderError] = {}  # provider -> the auth or quota error that ruled it out

    def _options(self, spec: TaskSpec, est: int) -> list[ModelOption]:
        options = [
            o for o in self.routes.options(spec.task) if o.provider not in self._disabled and o.fits(est, spec.max_output_tokens)
        ]
        return options if self.routes.fallback else options[:1]

    def can_afford(self, spec: TaskSpec, input_text: str, attempts: int = 1) -> bool:
        """Whether `attempts` more attempts of this task fit the remaining budget, at the priciest model it may use."""
        est = estimate_tokens(spec.instructions, input_text, json.dumps(spec.schema))
        b = self.budget
        options = self._options(spec, est)
        if not options or b.attempts_left() < attempts:
            return False
        tokens = (est + spec.max_output_tokens) * attempts
        cost = max(b.model_cost(est, spec.max_output_tokens, o.price) for o in options) * attempts
        return (
            b.tokens_committed + b.tokens_reserved + tokens <= b.max_tokens
            and b.cost_committed + b.cost_reserved + cost <= b.max_cost_usd
        )

    def _no_model(self, spec: TaskSpec) -> ProviderError:
        for option in self.routes.options(spec.task):
            cause = self._disabled.get(option.provider)
            if cause is not None:
                message = f"{cause.message}; {cause.provider} was skipped for the rest of the run"
                return ProviderError(cause.provider, cause.kind, message, status_code=cause.status_code)
        return ProviderError("model", ErrorKind.bad_request, "request is larger than every configured model accepts")

    async def call(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, finalizing: bool = False) -> dict[str, Any]:
        est = estimate_tokens(spec.instructions, input_text, json.dumps(spec.schema))
        options = self._options(spec, est)
        if not options:
            raise self._no_model(spec)
        self.metrics.model_calls += 1
        while True:
            option = options.pop(0)
            try:
                # With another model left to try, a failed attempt falls back instead of retrying the same model.
                data = await self._call_model(option, spec, est, input_text, payload, finalizing=finalizing, retry=not options)
            except ProviderError as exc:
                if exc.kind in DISABLING_KINDS:
                    self._disabled[option.provider] = exc
                    options = [o for o in options if o.provider != option.provider]
                if not options or exc.kind in NO_FALLBACK_KINDS:
                    raise
                self.metrics.model_fallbacks += 1
                log(
                    logger,
                    logging.WARNING,
                    "model fallback",
                    task=spec.task.value,
                    failed=option.label,
                    error=exc.kind.value,
                    next=options[0].label,
                )
                continue
            self.metrics.models_used[option.label] = self.metrics.models_used.get(option.label, 0) + 1
            return data

    async def _call_model(
        self,
        option: ModelOption,
        spec: TaskSpec,
        est: int,
        input_text: str,
        payload: dict[str, Any],
        *,
        finalizing: bool,
        retry: bool,
    ) -> dict[str, Any]:
        pending: list[Reservation] = []

        def reserve() -> None:
            pending.append(self.budget.reserve_model_attempt(est, spec.max_output_tokens, option.price))

        async def attempt(timeout: float) -> dict[str, Any]:
            res = pending[-1]
            try:
                outcome = await option.client.generate(spec, input_text, payload, timeout=timeout)
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

        attempt_log = AttemptLog()
        try:
            return await call_with_retries(
                attempt,
                policy=self.policy if retry else replace(self.policy, max_attempts=1),
                deadline=self.deadline,
                preferred_timeout=self.timeout_s,
                finalizing=finalizing,
                before_attempt=reserve,
                log=attempt_log,
            )
        finally:
            for res in pending:
                # A wait_for timeout cancels the attempt before it settles.
                self.budget.settle_model(res, None, None)
            self.metrics.retries += attempt_log.retries
            self.metrics.input_tokens = self.budget.input_tokens
            self.metrics.output_tokens = self.budget.output_tokens
            self.metrics.cost_uncertain = self.budget.cost_uncertain
