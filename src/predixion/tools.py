"""The two research tools: `search_web` and `read_sources`.

Provider adapters translate HTTP into typed outcomes or classified
`ProviderError`s and never retry on their own. `ToolRunner` owns retries,
caching, credit accounting, and per-item failure reporting for one run.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import TAVILY_BASE_URL
from .contracts import (
    ExecutionMetrics,
    ExtractedPage,
    FaultInjection,
    ItemFailure,
    SearchArgs,
    SearchHit,
    ToolName,
    ToolResult,
)
from .reliability import (
    AttemptLog,
    Budget,
    BudgetExhausted,
    Deadline,
    ErrorKind,
    ProviderError,
    RetryPolicy,
    call_with_retries,
    classify_http_status,
    parse_retry_after,
)
from .urls import canonicalize_url, is_safe_public_url

SEARCH_CREDITS = 1.0  # basic-depth search
URLS_PER_EXTRACT_CREDIT = 5  # basic-depth extract bills one credit per five successful URLs
MAX_EXTRACT_URLS = 20
MAX_ERROR_DETAIL = 200


@dataclass
class SearchOutcome:
    hits: list[SearchHit]
    credits: float | None = None


@dataclass
class ExtractOutcome:
    pages: list[ExtractedPage]
    failures: list[ItemFailure] = field(default_factory=list)
    credits: float | None = None


class SearchProvider(Protocol):
    name: str

    async def search(self, args: SearchArgs, *, timeout: float) -> SearchOutcome: ...


class ExtractProvider(Protocol):
    name: str

    async def extract(self, urls: list[str], *, timeout: float, query: str | None = None) -> ExtractOutcome: ...


# ---------------------------------------------------------------------------
# Tavily


def _safe_detail(response: httpx.Response) -> str:
    """Short, provider-supplied error text. Request headers (the API key) are never included."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    detail: Any = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, dict):
        detail = detail.get("error") or detail.get("message") or ""
    text = str(detail).strip().replace("\n", " ")
    return f"HTTP {response.status_code}: {text[:MAX_ERROR_DETAIL]}" if text else f"HTTP {response.status_code}"


class TavilyClient:
    """Tavily Search and Extract over REST, on one shared connection pool."""

    name = "tavily"

    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._http = http or httpx.AsyncClient(
            base_url=TAVILY_BASE_URL,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self._owns_http = http is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _post(self, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            response = await self._http.post(
                path,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)),
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, ErrorKind.timeout, "request timed out") from exc
        except httpx.TransportError as exc:
            raise ProviderError(self.name, ErrorKind.connection, type(exc).__name__) from exc
        if response.status_code != 200:
            raise classify_http_status(
                self.name,
                response.status_code,
                _safe_detail(response),
                parse_retry_after(response.headers.get("retry-after")),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(self.name, ErrorKind.malformed_response, "response was not JSON") from exc
        if not isinstance(body, dict):
            raise ProviderError(self.name, ErrorKind.malformed_response, "unexpected response shape")
        return body

    @staticmethod
    def _credits(body: dict[str, Any]) -> float | None:
        usage = body.get("usage")
        if isinstance(usage, dict) and isinstance(usage.get("credits"), int | float):
            return float(usage["credits"])
        return None

    async def search(self, args: SearchArgs, *, timeout: float) -> SearchOutcome:
        payload: dict[str, Any] = {
            "query": args.query,
            "search_depth": "basic",
            "topic": args.topic,
            "max_results": args.max_results,
            "include_answer": False,  # the application synthesizes; provider answers are not evidence
            "include_raw_content": False,
            "include_images": False,
            "include_usage": True,
        }
        if args.time_range:
            payload["time_range"] = args.time_range
        body = await self._post("/search", payload, timeout)
        results = body.get("results")
        if not isinstance(results, list):
            raise ProviderError(self.name, ErrorKind.malformed_response, "search response missing results")
        hits = []
        for item in results:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                continue
            score = item.get("score")
            hits.append(
                SearchHit(
                    url=item["url"][:2_048],
                    title=str(item.get("title") or "")[:300],
                    snippet=str(item.get("content") or "")[:1_000],
                    score=float(score) if isinstance(score, int | float) else None,
                    published_date=str(item["published_date"])[:40] if item.get("published_date") else None,
                )
            )
        return SearchOutcome(hits=hits, credits=self._credits(body))

    async def extract(self, urls: list[str], *, timeout: float, query: str | None = None) -> ExtractOutcome:
        del query  # full page content is requested; passage selection happens in the application
        payload: dict[str, Any] = {
            "urls": urls[:MAX_EXTRACT_URLS],
            "extract_depth": "basic",
            "format": "markdown",
            "include_images": False,
            "include_usage": True,
            "timeout": max(1.0, min(60.0, timeout - 2.0)),
        }
        body = await self._post("/extract", payload, timeout)
        pages: list[ExtractedPage] = []
        failures: list[ItemFailure] = []
        for item in body.get("results") or []:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                content = item.get("raw_content")
                if isinstance(content, str) and content.strip():
                    pages.append(ExtractedPage(url=item["url"], content=content))
                else:
                    failures.append(ItemFailure(item=item["url"], error="empty content"))
        for item in body.get("failed_results") or []:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                error = str(item.get("error") or "extraction failed")[:MAX_ERROR_DETAIL]
                failures.append(ItemFailure(item=item["url"], error=error, retryable="timeout" in error.lower()))
        returned = {p.url for p in pages} | {f.item for f in failures}
        for url in urls:
            if url not in returned:
                failures.append(ItemFailure(item=url, error="not returned by provider"))
        return ExtractOutcome(pages=pages, failures=failures, credits=self._credits(body))


# ---------------------------------------------------------------------------
# Fault injection (tests and demos only; gated by configuration)


class FaultySearch:
    def __init__(self, inner: SearchProvider, mode: str) -> None:
        self.inner, self.mode, self.name = inner, mode, inner.name

    async def search(self, args: SearchArgs, *, timeout: float) -> SearchOutcome:
        if self.mode == "unavailable":
            raise ProviderError(self.name, ErrorKind.server_error, "injected: HTTP 503", status_code=503)
        if self.mode == "rate_limited":
            raise ProviderError(self.name, ErrorKind.rate_limited, "injected: HTTP 429", status_code=429, retry_after=0.05)
        if self.mode == "auth":
            raise ProviderError(self.name, ErrorKind.auth, "injected: HTTP 401", status_code=401)
        if self.mode == "empty":
            return SearchOutcome(hits=[], credits=0)
        return await self.inner.search(args, timeout=timeout)


class FaultyExtract:
    def __init__(self, inner: ExtractProvider, mode: str) -> None:
        self.inner, self.mode, self.name = inner, mode, inner.name

    async def extract(self, urls: list[str], *, timeout: float, query: str | None = None) -> ExtractOutcome:
        if self.mode == "unavailable":
            raise ProviderError(self.name, ErrorKind.server_error, "injected: HTTP 503", status_code=503)
        if self.mode == "all_failed":
            return ExtractOutcome(
                pages=[], failures=[ItemFailure(item=u, error="injected: fetch failed") for u in urls], credits=0
            )
        outcome = await self.inner.extract(urls, timeout=timeout, query=query)
        if self.mode == "partial":
            keep = math.ceil(len(outcome.pages) / 2)
            dropped = outcome.pages[keep:]
            outcome.pages = outcome.pages[:keep]
            outcome.failures += [ItemFailure(item=p.url, error="injected: fetch failed") for p in dropped]
        return outcome


def apply_faults(
    search: SearchProvider, extract: ExtractProvider, fault: FaultInjection | None
) -> tuple[SearchProvider, ExtractProvider]:
    if fault is None:
        return search, extract
    if fault.search != "none":
        search = FaultySearch(search, fault.search)
    if fault.extract != "none":
        extract = FaultyExtract(extract, fault.extract)
    return search, extract


# ---------------------------------------------------------------------------
# Cache


class TTLCache:
    """Small in-process LRU cache with per-entry expiry. Public web content only."""

    def __init__(self, max_entries: int, clock=time.monotonic) -> None:
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_entries
        self._clock = clock

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < self._clock():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl_s: float) -> None:
        if self._max <= 0 or ttl_s <= 0:
            return
        self._data[key] = (self._clock() + ttl_s, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)


def _search_key(provider: str, args: SearchArgs) -> str:
    return "search:" + json.dumps(
        [provider, " ".join(args.query.casefold().split()), args.max_results, args.topic, args.time_range]
    )


# ---------------------------------------------------------------------------
# Per-run tool execution


class ToolRunner:
    """Executes tool calls for one run under its deadline, budget, and concurrency limit."""

    def __init__(
        self,
        *,
        search: SearchProvider,
        extract: ExtractProvider,
        budget: Budget,
        deadline: Deadline,
        metrics: ExecutionMetrics,
        policy: RetryPolicy,
        search_timeout_s: float,
        extract_timeout_s: float,
        concurrency: int,
        cache: TTLCache | None = None,
        search_ttl_s: float = 0,
        extract_ttl_s: float = 0,
    ) -> None:
        self.search_provider = search
        self.extract_provider = extract
        self.budget = budget
        self.deadline = deadline
        self.metrics = metrics
        self.policy = policy
        self.search_timeout_s = search_timeout_s
        self.extract_timeout_s = extract_timeout_s
        self.semaphore = asyncio.Semaphore(concurrency)
        self.cache = cache
        self.search_ttl_s = search_ttl_s
        self.extract_ttl_s = extract_ttl_s

    def _charge(self, credits: float | None, estimate: float) -> float:
        used = estimate if credits is None else credits
        self.budget.charge_credits(used)
        self.metrics.tavily_credits += used
        return used

    async def search_web(self, args: SearchArgs) -> ToolResult:
        started = time.perf_counter()
        self.metrics.search_calls += 1
        key = _search_key(self.search_provider.name, args)
        if self.cache is not None and (cached := self.cache.get(key)) is not None:
            self.metrics.cache_hits += 1
            return ToolResult(
                tool=ToolName.search_web,
                ok=True,
                items_requested=1,
                items_succeeded=1,
                hits=cached,
                cached=True,
                attempts=0,
                credits=0,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        self.metrics.cache_misses += 1
        if not self.budget.can_spend_credits(SEARCH_CREDITS):
            raise BudgetExhausted("cost")
        log = AttemptLog()
        async with self.semaphore:
            try:
                outcome = await call_with_retries(
                    lambda timeout: self.search_provider.search(args, timeout=timeout),
                    policy=self.policy,
                    deadline=self.deadline,
                    preferred_timeout=self.search_timeout_s,
                    log=log,
                )
            except ProviderError as exc:
                self.metrics.retries += log.retries
                return ToolResult(
                    tool=ToolName.search_web,
                    ok=False,
                    items_requested=1,
                    items_succeeded=0,
                    error=exc.message,
                    error_kind=str(exc.kind),
                    attempts=log.attempts,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
        self.metrics.retries += log.retries
        credits = self._charge(outcome.credits, SEARCH_CREDITS)
        if self.cache is not None and outcome.hits:
            self.cache.set(key, outcome.hits, self.search_ttl_s)
        return ToolResult(
            tool=ToolName.search_web,
            ok=True,
            items_requested=1,
            items_succeeded=1,
            hits=outcome.hits,
            attempts=log.attempts,
            credits=credits,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def read_sources(self, urls: list[str], query: str | None = None) -> ToolResult:
        """Read already-validated source URLs. Unsafe URLs are refused before any provider call."""
        started = time.perf_counter()
        self.metrics.extract_calls += 1
        self.metrics.pages_requested += len(urls)
        pages: list[ExtractedPage] = []
        failures: list[ItemFailure] = []
        to_fetch: list[str] = []
        for url in urls:
            if not is_safe_public_url(url):
                failures.append(ItemFailure(item=url, error="refused: unsafe URL"))
                continue
            cached = self.cache.get("extract:" + canonicalize_url(url)) if self.cache is not None else None
            if cached is not None:
                self.metrics.cache_hits += 1
                pages.append(ExtractedPage(url=url, content=cached))
            else:
                self.metrics.cache_misses += 1
                to_fetch.append(url)

        attempts = 0
        credits_used = 0.0
        error: str | None = None
        error_kind: str | None = None
        if to_fetch:
            estimate = math.ceil(len(to_fetch) / URLS_PER_EXTRACT_CREDIT)
            if not self.budget.can_spend_credits(estimate):
                raise BudgetExhausted("cost")
            log = AttemptLog()
            async with self.semaphore:
                try:
                    outcome = await call_with_retries(
                        lambda timeout: self.extract_provider.extract(to_fetch, timeout=timeout, query=query),
                        policy=self.policy,
                        deadline=self.deadline,
                        preferred_timeout=self.extract_timeout_s,
                        log=log,
                    )
                except ProviderError as exc:
                    outcome = None
                    error, error_kind = exc.message, str(exc.kind)
                    failures += [ItemFailure(item=u, error=exc.message, retryable=exc.retryable) for u in to_fetch]
            attempts = log.attempts
            self.metrics.retries += log.retries
            if outcome is not None:
                succeeded = len(outcome.pages)
                credits_used = self._charge(outcome.credits, math.ceil(succeeded / URLS_PER_EXTRACT_CREDIT))
                requested = {canonicalize_url(u): u for u in to_fetch}
                for page in outcome.pages:
                    # Map provider-returned URLs back to the URL we asked for.
                    original = requested.get(canonicalize_url(page.url), page.url)
                    pages.append(ExtractedPage(url=original, content=page.content))
                    if self.cache is not None:
                        self.cache.set("extract:" + canonicalize_url(original), page.content, self.extract_ttl_s)
                for failure in outcome.failures:
                    original = requested.get(canonicalize_url(failure.item), failure.item)
                    failures.append(ItemFailure(item=original, error=failure.error, retryable=failure.retryable))

        self.metrics.pages_read += len(pages)
        return ToolResult(
            tool=ToolName.read_sources,
            ok=bool(pages),
            items_requested=len(urls),
            items_succeeded=len(pages),
            pages=pages,
            failures=failures,
            error=error,
            error_kind=error_kind,
            attempts=attempts,
            cached=bool(pages) and not to_fetch,
            credits=credits_used,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
