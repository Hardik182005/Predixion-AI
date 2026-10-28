"""Provider adapters against mocked HTTP. No network access."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from openai import AsyncOpenAI

from predixion.contracts import SearchArgs
from predixion.llm import GroqModel, OpenAIModel
from predixion.prompts import Task, spec
from predixion.reliability import ErrorKind, ProviderError
from predixion.tools import TavilyClient

TAVILY_KEY = "tvly-test-secret-key"
OPENAI_KEY = "sk-test-secret-key"
GROQ_KEY = "gsk_testsecretkey123"

Handler = Callable[[httpx.Request], httpx.Response]


def tavily(handler: Handler) -> TavilyClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.tavily.test")
    return TavilyClient(TAVILY_KEY, http=http)


async def _search_error(handler: Handler) -> ProviderError:
    with pytest.raises(ProviderError) as info:
        await tavily(handler).search(SearchArgs(query="vector databases"), timeout=5)
    assert TAVILY_KEY not in str(info.value)
    return info.value


# ---------------------------------------------------------------------------
# Tavily


async def test_search_maps_results_and_sends_bearer_key() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://a.example/x",
                        "title": "A",
                        "content": "snippet",
                        "score": 0.8,
                        "published_date": "2026-01-02",
                    },
                    {"title": "no url"},
                    "not a dict",
                ],
                "usage": {"credits": 1},
            },
        )

    outcome = await tavily(handler).search(SearchArgs(query="vector databases", time_range="year"), timeout=5)
    assert seen["auth"] == f"Bearer {TAVILY_KEY}"
    assert seen["body"]["include_answer"] is False
    assert seen["body"]["time_range"] == "year"
    assert [(h.url, h.score, h.published_date) for h in outcome.hits] == [("https://a.example/x", 0.8, "2026-01-02")]
    assert outcome.credits == 1.0


async def test_rate_limit_carries_retry_after() -> None:
    error = await _search_error(
        lambda r: httpx.Response(429, headers={"retry-after": "3"}, json={"detail": {"error": "slow down"}})
    )
    assert (error.kind, error.retry_after, error.retryable) == (ErrorKind.rate_limited, 3.0, True)
    assert "slow down" in error.message


@pytest.mark.parametrize(
    ("status", "kind", "retryable"),
    [
        (500, ErrorKind.server_error, True),
        (502, ErrorKind.server_error, True),
        (401, ErrorKind.auth, False),
        (432, ErrorKind.quota, False),
        (400, ErrorKind.bad_request, False),
    ],
)
async def test_http_errors_are_classified(status: int, kind: ErrorKind, retryable: bool) -> None:
    error = await _search_error(lambda r: httpx.Response(status, text="<html>error page</html>"))
    assert (error.kind, error.retryable, error.status_code) == (kind, retryable, status)


async def test_timeout_and_connection_errors() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert (await _search_error(timeout)).kind == ErrorKind.timeout
    assert (await _search_error(refused)).kind == ErrorKind.connection


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["a", "list"]),
        httpx.Response(200, json={"answer": "no results key"}),
        httpx.Response(200, json={"results": "not a list"}),
    ],
)
async def test_malformed_search_responses(response: httpx.Response) -> None:
    error = await _search_error(lambda r: response)
    assert error.kind == ErrorKind.malformed_response


async def test_extract_reports_partial_failures() -> None:
    urls = ["https://a.example/1", "https://b.example/2", "https://c.example/3", "https://d.example/4"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["urls"] == urls
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": urls[0], "raw_content": "# Page\nUseful text."},
                    {"url": urls[1], "raw_content": "   "},
                ],
                "failed_results": [{"url": urls[2], "error": "Request timeout while fetching"}],
            },
        )

    outcome = await tavily(handler).extract(urls, timeout=10)
    assert [p.url for p in outcome.pages] == [urls[0]]
    failures = {f.item: f for f in outcome.failures}
    assert failures[urls[1]].error == "empty content"
    assert failures[urls[2]].retryable
    assert failures[urls[3]].error == "not returned by provider"


# ---------------------------------------------------------------------------
# OpenAI Responses API


def _response(**overrides) -> dict:
    body = {
        "id": "resp_test",
        "object": "response",
        "created_at": 1_790_000_000,
        "model": "gpt-test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps({"ok": True}), "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
    }
    body.update(overrides)
    return body


def openai_model(handler: Handler) -> OpenAIModel:
    model = OpenAIModel(OPENAI_KEY, "gpt-test", "low")
    model._client = AsyncOpenAI(
        api_key=OPENAI_KEY,
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return model


async def _generate(handler: Handler):
    return await openai_model(handler).generate(spec(Task.plan, today="2026-10-28"), "question", {}, timeout=5)


async def _model_error(handler: Handler) -> ProviderError:
    with pytest.raises(ProviderError) as info:
        await _generate(handler)
    assert OPENAI_KEY not in str(info.value)
    return info.value


async def test_model_success_sends_strict_schema_without_storage() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_response())

    outcome = await _generate(handler)
    assert outcome.data == {"ok": True}
    assert (outcome.input_tokens, outcome.output_tokens) == (120, 30)
    assert seen["store"] is False
    assert seen["text"]["format"]["strict"] is True
    assert seen["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (401, {"error": {"message": "bad key", "type": "invalid_request_error", "code": "invalid_api_key"}}, ErrorKind.auth),
        (429, {"error": {"message": "quota", "type": "insufficient_quota", "code": "insufficient_quota"}}, ErrorKind.quota),
        (429, {"error": {"message": "slow", "type": "requests", "code": "rate_limit_exceeded"}}, ErrorKind.rate_limited),
        (500, {"error": {"message": "oops", "type": "server_error", "code": None}}, ErrorKind.server_error),
        (400, {"error": {"message": "bad schema", "type": "invalid_request_error", "code": None}}, ErrorKind.bad_request),
    ],
)
async def test_model_http_errors(status: int, body: dict, kind: ErrorKind) -> None:
    error = await _model_error(lambda r: httpx.Response(status, json=body, headers={"retry-after": "4"}))
    assert error.kind == kind
    if kind == ErrorKind.rate_limited:
        assert error.retry_after == 4.0


async def test_model_timeout_and_connection_errors() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert (await _model_error(timeout)).kind == ErrorKind.timeout
    assert (await _model_error(refused)).kind == ErrorKind.connection


async def test_model_output_that_is_not_json_is_malformed() -> None:
    body = _response()
    body["output"][0]["content"][0]["text"] = "Sure! Here is the plan: ..."
    error = await _model_error(lambda r: httpx.Response(200, json=body))
    assert error.kind == ErrorKind.malformed_response
    assert error.retryable
    assert error.usage == (120, 30)


async def test_model_refusal_and_incomplete_are_not_retried() -> None:
    refusal = _response()
    refusal["output"][0]["content"] = [{"type": "refusal", "refusal": "I can't help with that."}]
    error = await _model_error(lambda r: httpx.Response(200, json=refusal))
    assert (error.kind, error.retryable) == (ErrorKind.refusal, False)

    incomplete = _response(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    error = await _model_error(lambda r: httpx.Response(200, json=incomplete))
    assert (error.kind, error.retryable) == (ErrorKind.incomplete, False)
    assert "max_output_tokens" in error.message


# ---------------------------------------------------------------------------
# Groq


def _completion(content: str | None = '{"ok": true}', finish_reason: str = "stop", **message) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_790_000_000,
        "model": "openai/gpt-oss-120b",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content, **message}, "finish_reason": finish_reason}
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    }


def groq_model(handler: Handler, effort: str | None = "low") -> GroqModel:
    model = GroqModel(GROQ_KEY, "openai/gpt-oss-120b", effort)
    model._client = AsyncOpenAI(
        api_key=GROQ_KEY,
        base_url="https://api.groq.test/openai/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return model


async def _groq_generate(handler: Handler, effort: str | None = "low"):
    return await groq_model(handler, effort).generate(spec(Task.plan, today="2026-10-28"), "question", {}, timeout=5)


async def _groq_error(handler: Handler) -> ProviderError:
    with pytest.raises(ProviderError) as info:
        await _groq_generate(handler)
    assert GROQ_KEY not in str(info.value)
    assert info.value.provider == "groq"
    return info.value


async def test_groq_sends_a_strict_schema_and_reads_usage() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers["authorization"]
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_completion())

    outcome = await _groq_generate(handler)
    assert outcome.data == {"ok": True}
    assert (outcome.input_tokens, outcome.output_tokens) == (120, 30)
    assert seen["path"] == "/openai/v1/chat/completions"
    assert seen["auth"] == f"Bearer {GROQ_KEY}"
    plan = spec(Task.plan, today="2026-10-28")
    assert seen["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "plan", "schema": plan.schema, "strict": True},
    }
    assert [m["role"] for m in seen["messages"]] == ["system", "user"]
    assert seen["messages"][1]["content"] == "question"
    assert seen["max_completion_tokens"] == plan.max_output_tokens
    assert seen["reasoning_effort"] == "low"
    assert seen["include_reasoning"] is False
    assert "store" not in seen


async def test_groq_maps_reasoning_effort_to_supported_values() -> None:
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content).get("reasoning_effort"))
        return httpx.Response(200, json=_completion())

    for effort in ("minimal", "high", None):
        await _groq_generate(handler, effort)
    assert seen == ["low", "high", None]


@pytest.mark.parametrize(
    ("status", "kind", "retryable"),
    [
        (401, ErrorKind.auth, False),
        (429, ErrorKind.rate_limited, True),
        (498, ErrorKind.rate_limited, True),  # Groq: capacity exceeded
        (413, ErrorKind.bad_request, False),  # request larger than the tokens-per-minute limit
        (503, ErrorKind.server_error, True),
    ],
)
async def test_groq_http_errors(status: int, kind: ErrorKind, retryable: bool) -> None:
    body = {"error": {"message": "x", "type": "invalid_request_error", "code": "rate_limit_exceeded"}}
    error = await _groq_error(lambda r: httpx.Response(status, json=body, headers={"retry-after": "3"}))
    assert (error.kind, error.retryable) == (kind, retryable)
    if kind == ErrorKind.rate_limited:
        assert error.retry_after == 3.0


async def test_groq_timeout_and_connection_errors() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert (await _groq_error(timeout)).kind == ErrorKind.timeout
    assert (await _groq_error(refused)).kind == ErrorKind.connection


async def test_groq_truncated_refused_and_malformed_outputs() -> None:
    error = await _groq_error(lambda r: httpx.Response(200, json=_completion('{"ok": tr', finish_reason="length")))
    assert (error.kind, error.retryable, error.usage) == (ErrorKind.incomplete, False, (120, 30))

    error = await _groq_error(lambda r: httpx.Response(200, json=_completion(None, refusal="I can't help with that.")))
    assert (error.kind, error.retryable) == (ErrorKind.refusal, False)

    error = await _groq_error(lambda r: httpx.Response(200, json=_completion("Sure! Here is the plan")))
    assert (error.kind, error.retryable, error.usage) == (ErrorKind.malformed_response, True, (120, 30))

    error = await _groq_error(lambda r: httpx.Response(200, json=_completion("[1, 2]")))
    assert error.kind == ErrorKind.malformed_response
