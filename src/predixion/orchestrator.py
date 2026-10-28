"""The research workflow.

validate -> plan -> (search -> filter -> read -> extract -> assess -> follow_up)* ->
synthesize -> verify -> repair (once) -> finalize

Control flow is ordinary application code with explicit stages. The model is
asked for structured outputs at fixed points (plan, extract, follow-up,
synthesize, verify, repair); it never invokes tools or chooses how many rounds
run. Every stop condition is checked here.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from .config import PROMPT_VERSION, Settings
from .contracts import (
    CheckedText,
    ClaimDisposition,
    ClaimKind,
    Conflict,
    CoverageStatus,
    Criterion,
    CriterionCoverage,
    CriterionKind,
    EventType,
    Evidence,
    ExecutionInfo,
    ExecutionMetrics,
    Finding,
    Mode,
    Passage,
    PlannedQuery,
    ResearchPlan,
    ResearchReport,
    ResearchRequest,
    RunStatus,
    SearchArgs,
    Source,
    SourceState,
    SourceTier,
    Stage,
    StageTiming,
    StopReason,
    SupportVerdict,
    TaskType,
    VerificationSummary,
)
from .grounding import (
    ClaimRef,
    Draft,
    apply_verdict,
    assess_confidence,
    check_references,
    compute_coverage,
    decide_status,
    enumerate_claims,
    finalize_draft,
    gap_criteria,
    keep_valid_conflicts,
    parse_draft,
    polarity_conflicts,
    required_satisfied,
    validate_evidence,
)
from .llm import FaultyModel, ModelCaller, ModelClient, ModelRoutes
from .prompts import Task, attr, dump, fence, render_sections, spec
from .reliability import Budget, BudgetExhausted, Deadline, DeadlineReached, ErrorKind, ProviderError, RetryPolicy
from .sources import (
    MIN_USEFUL_CHARS,
    chunk_passages,
    classify_source,
    clean_content,
    content_hash,
    find_page_date,
    has_non_text_extension,
    jaccard,
    looks_paywalled,
    parse_date,
    screen_injection,
    select_passages,
    shingles,
    term_overlap,
    tokenize,
)
from .tools import ExtractProvider, SearchProvider, ToolRunner, TTLCache, apply_faults
from .urls import UnsafeURL, canonicalize_url, hostname, registrable_domain, validate_public_url

EmitFn = Callable[[EventType, Stage | None, str, dict[str, Any] | None], None]

TIER_WEIGHT = {SourceTier.high: 0.2, SourceTier.medium: 0.1, SourceTier.low: 0.0}
MAX_PER_DOMAIN = 2
NEAR_DUPLICATE_JACCARD = 0.85
MIN_RESEARCH_SECONDS_FOR_ROUND = 25.0
MAX_CRITERIA = 8  # contracts.ResearchPlan allows at most 8; compound criteria split into parts share this bound
MAX_CRITERION_PARTS = 4
PROVIDER_FAILURE_KINDS = {
    ErrorKind.auth: StopReason.provider_auth_error,
    ErrorKind.quota: StopReason.provider_unavailable,
}
# Stops that end research before it could finish. With no evidence, they are reported as failed,
# never as "insufficient evidence" (which is a verdict about sources that were actually read).
CUT_OFF_STOP_REASONS = frozenset(
    {
        StopReason.provider_unavailable,
        StopReason.provider_auth_error,
        StopReason.deadline_reached,
        StopReason.budget_exhausted,
        StopReason.model_output_invalid,
        StopReason.internal_error,
    }
)


@dataclass
class Providers:
    search: SearchProvider
    extract: ExtractProvider
    model: ModelClient  # the primary model, reported in the run's execution info
    mode: Mode
    cache: TTLCache | None = None
    routes: ModelRoutes | None = None  # per-task models and fallbacks; None runs every task on `model`


def _now() -> datetime:
    return datetime.now(UTC)


class ResearchRun:
    """One research run. Not reused across runs."""

    def __init__(
        self,
        run_id: str,
        request: ResearchRequest,
        settings: Settings,
        providers: Providers,
        emit: EmitFn,
        *,
        today: date | None = None,
    ) -> None:
        self.run_id = run_id
        self.request = request
        self.settings = settings
        self.mode = providers.mode
        self.today = today or _now().date()
        self._emit_fn = emit
        self._started_perf = time.perf_counter()

        fault = request.fault if settings.fault_injection_allowed else None
        search, extract = apply_faults(providers.search, providers.extract, fault)
        routes = providers.routes or ModelRoutes.single(providers.model, providers.mode.value)
        if fault is not None and fault.model != "none":
            fault_mode = fault.model
            routes = routes.wrap(lambda client: FaultyModel(client, fault_mode))
        self.model_name = providers.model.model
        self.sdk_version = providers.model.sdk_version

        self.max_rounds = min(request.max_rounds or settings.max_rounds, 4)
        self.deadline = Deadline(settings.run_deadline_s, settings.finalize_reserve_s)
        self.budget = Budget(
            max_model_attempts=settings.max_model_attempts,
            max_tokens=settings.max_tokens_per_run,
            max_cost_usd=settings.max_cost_usd_per_run,
            max_pages=settings.max_pages_per_run,
            input_usd_per_mtok=settings.model_input_usd_per_mtok if self.mode == Mode.live else 0.0,
            output_usd_per_mtok=settings.model_output_usd_per_mtok if self.mode == Mode.live else 0.0,
            usd_per_credit=settings.tavily_usd_per_credit if self.mode == Mode.live else 0.0,
        )
        self.metrics = ExecutionMetrics(started_at=_now())
        policy = RetryPolicy(max_attempts=settings.retry_max_attempts)
        self.tools = ToolRunner(
            search=search,
            extract=extract,
            budget=self.budget,
            deadline=self.deadline,
            metrics=self.metrics,
            policy=policy,
            search_timeout_s=settings.search_timeout_s,
            extract_timeout_s=settings.extract_timeout_s,
            concurrency=settings.max_concurrency,
            cache=providers.cache,
            search_ttl_s=settings.cache_ttl_search_s,
            extract_ttl_s=settings.cache_ttl_extract_s,
        )
        self.models = ModelCaller(
            routes,
            budget=self.budget,
            deadline=self.deadline,
            metrics=self.metrics,
            policy=policy,
            timeout_s=settings.model_timeout_s,
        )

        self.plan: ResearchPlan | None = None
        self.sources: dict[str, Source] = {}
        self.by_canonical: dict[str, str] = {}
        self.passages: dict[str, list[Passage]] = {}
        self.passage_index: dict[str, Passage] = {}
        self.hashes: dict[str, str] = {}
        self.shingle_sets: dict[str, set[int]] = {}
        self.evidence: list[Evidence] = []
        self.queries: list[PlannedQuery] = []
        self.round = 0
        self.stop_reason: StopReason | None = None
        self.stop_detail: str | None = None
        self.notes: list[str] = []  # system limitations gathered during the run
        self.provider_errors: list[str] = []
        self.read_errors: list[str] = []  # extract calls that failed as a whole
        self.coverage: list[CriterionCoverage] = []
        self.stage: Stage | None = None

    # ------------------------------------------------------------------
    # Events and stages

    def emit(self, type_: EventType, message: str, data: dict[str, Any] | None = None) -> None:
        if self.metrics.first_event_ms is None:
            self.metrics.first_event_ms = round((time.perf_counter() - self._started_perf) * 1000, 1)
        self._emit_fn(type_, self.stage, message, data)

    @asynccontextmanager
    async def _stage(self, stage: Stage, message: str):
        self.stage = stage
        self.emit(EventType.stage, message)
        started = time.perf_counter()
        try:
            yield
        finally:
            self.metrics.stage_timings.append(StageTiming(stage=stage, ms=round((time.perf_counter() - started) * 1000, 1)))

    def _stop(self, reason: StopReason, detail: str) -> None:
        if self.stop_reason is None:
            self.stop_reason, self.stop_detail = reason, detail

    # ------------------------------------------------------------------
    # Entry point

    async def execute(self) -> ResearchReport:
        # The run may have been constructed while queued; its time limit and timings start now.
        self._started_perf = time.perf_counter()
        self.deadline.restart()
        self.metrics.started_at = _now()
        self.emit(EventType.status, "Run started", {"status": "running", "mode": self.mode.value})
        async with self._stage(Stage.validate, "Validating request"):
            seeds = self._validate_seeds()

        try:
            async with self._stage(Stage.plan, "Planning research"):
                self.plan = await self._plan()
        except (ProviderError, BudgetExhausted, DeadlineReached) as exc:
            return self._failure_report(exc, during="planning")

        self.emit(EventType.plan, "Research plan ready", self._plan_event(self.plan))
        await self._research(seeds)
        return await self._conclude()

    # ------------------------------------------------------------------
    # Validation and planning

    def _validate_seeds(self) -> list[str]:
        safe = []
        for url in self.request.seed_urls:
            try:
                safe.append(validate_public_url(url.strip()))
            except UnsafeURL as exc:
                self.notes.append(f"A provided URL was not used ({exc}).")
                self.emit(EventType.warning, f"Ignored a provided URL: {exc}")
        return safe

    async def _plan(self) -> ResearchPlan:
        s = spec(
            Task.plan,
            today=self.today.isoformat(),
            max_queries=self.settings.max_queries_per_round,
            max_output_tokens=self.settings.max_output_tokens,
        )
        input_text = render_sections([("question", fence(self.request.question))])
        data = await self.models.call(s, input_text, {"question": self.request.question})
        return normalize_plan(data, question=self.request.question, max_queries=self.settings.max_queries_per_round)

    def _plan_event(self, plan: ResearchPlan) -> dict[str, Any]:
        return {
            "task_type": plan.task_type.value,
            "interpretation": plan.interpretation,
            "ambiguity_note": plan.ambiguity_note,
            "criteria": [
                {"id": c.id, "description": c.description, "kind": c.kind.value, "required": c.required} for c in plan.criteria
            ],
            "queries": [{"id": q.id, "text": q.text} for q in plan.queries],
            "entities": plan.candidate_entities,
        }

    # ------------------------------------------------------------------
    # Research rounds

    def _terms(self) -> list[str]:
        assert self.plan is not None
        terms = [self.request.question, *self.plan.candidate_entities]
        for c in self.plan.criteria:
            terms += [c.description, *c.key_terms]
        return terms

    def _round_page_limit(self, round_no: int) -> int:
        remaining = self.budget.max_pages - self.budget.pages_reserved
        if round_no == 1 and self.max_rounds > 1:
            return min(remaining, max(3, math.ceil(self.budget.max_pages * 0.625)))
        return remaining

    async def _research(self, seeds: list[str]) -> None:
        assert self.plan is not None
        pending_queries = [q for q in self.plan.queries]
        pending_reads: list[str] = [sid for url in seeds if (sid := self._register_url(url, round_no=1, seed=True))]
        try:
            for round_no in range(1, self.max_rounds + 1):
                self.round = round_no
                self.metrics.rounds = round_no
                new_sources = await self._run_round(round_no, pending_queries, pending_reads)
                if round_no == 1 and not self.evidence and (self._all_searches_failed() or self._reader_down(new_sources)):
                    return
                new_evidence = await self._extract_round(new_sources, round_no)

                async with self._stage(Stage.assess, f"Assessing coverage after round {round_no}"):
                    self.coverage = self._coverage()
                    self.emit(EventType.coverage, self._coverage_message(), self._coverage_event())
                if required_satisfied(self.coverage):
                    self._stop(StopReason.criteria_satisfied, "All required criteria have supporting evidence.")
                    return
                if round_no > 1 and new_evidence == 0:
                    self._stop(StopReason.diminishing_returns, "The follow-up round found no new evidence.")
                    return
                if round_no == self.max_rounds:
                    self._stop(StopReason.rounds_exhausted, f"Reached the limit of {self.max_rounds} research rounds.")
                    return
                if self.deadline.research_remaining() < MIN_RESEARCH_SECONDS_FOR_ROUND:
                    self._stop(StopReason.deadline_reached, "Not enough time remained for another research round.")
                    return
                if self.budget.pages_reserved >= self.budget.max_pages:
                    self._stop(StopReason.page_budget_exhausted, f"Read the maximum of {self.budget.max_pages} pages.")
                    return
                async with self._stage(Stage.follow_up, "Choosing follow-up research for open gaps"):
                    pending_queries, pending_reads = await self._follow_up(round_no + 1)
                if not pending_queries and not pending_reads:
                    self._stop(StopReason.no_actionable_gaps, "No follow-up action was likely to close the remaining gaps.")
                    return
        except DeadlineReached:
            self._stop(StopReason.deadline_reached, "The run deadline was reached during research.")
            self.emit(EventType.warning, "Deadline reached; continuing with the evidence collected so far")
        except BudgetExhausted as exc:
            self._stop(StopReason.budget_exhausted, f"The per-run {exc.resource} budget was exhausted during research.")
            self.emit(EventType.warning, f"Budget limit reached ({exc.resource}); continuing with the evidence collected so far")
        except ProviderError as exc:
            reason = PROVIDER_FAILURE_KINDS.get(exc.kind, StopReason.provider_unavailable)
            self._stop(reason, f"{exc.provider} failed during research ({exc.kind}).")
            self.emit(EventType.warning, f"{exc.provider} failed ({exc.kind}); continuing with the evidence collected so far")

    def _all_searches_failed(self) -> bool:
        if self.metrics.search_calls and self.provider_errors and not self.sources:
            kinds = " ".join(self.provider_errors)
            reason = StopReason.provider_auth_error if "auth" in kinds else StopReason.provider_unavailable
            self._stop(reason, "Search failed for every query: " + "; ".join(sorted(set(self.provider_errors)))[:300])
            return True
        if not self.sources:
            self._stop(StopReason.no_relevant_sources, "Search returned no usable sources.")
            return True
        return False

    def _reader_down(self, new_sources: list[str]) -> bool:
        """The extract provider failed outright (not page by page) and nothing has been read."""
        if new_sources or not self.read_errors or any(s.state == SourceState.read for s in self.sources.values()):
            return False
        reason = StopReason.provider_auth_error if ErrorKind.auth in self.read_errors else StopReason.provider_unavailable
        self._stop(reason, "Page extraction failed for every request: " + "; ".join(sorted(set(self.read_errors)))[:300])
        return True

    async def _run_round(self, round_no: int, queries: list[PlannedQuery], reads: list[str]) -> list[str]:
        if queries:
            async with self._stage(Stage.search, f"Searching the web (round {round_no})"):
                await self._search_all(queries, round_no)
        async with self._stage(Stage.filter, "Filtering and ranking sources"):
            limit = self._round_page_limit(round_no)
            chosen = list(dict.fromkeys(reads))[:limit]
            if round_no > 1 and queries:
                # Spread follow-up slots across the gaps: the best new hit of each gap query first, then by rank.
                chosen += self._best_per_query(queries, limit - len(chosen), exclude=set(chosen))
            prefer = [q.text for q in queries] if round_no > 1 else None
            chosen += self._select_candidates(limit - len(chosen), exclude=set(chosen), prefer=prefer)
            granted = self.budget.reserve_pages(len(chosen))
            chosen = chosen[:granted]
        if not chosen:
            return []
        async with self._stage(Stage.read, f"Reading {len(chosen)} source{'s' if len(chosen) != 1 else ''}"):
            return await self._read(chosen, round_no)

    async def _search_all(self, queries: list[PlannedQuery], round_no: int) -> None:
        self.queries += queries
        results = await asyncio.gather(
            *(self.tools.search_web(SearchArgs(query=q.text, max_results=6, topic=q.topic)) for q in queries),
            return_exceptions=True,
        )
        for q, result in zip(queries, results, strict=True):
            if isinstance(result, BudgetExhausted | DeadlineReached):
                raise result
            if isinstance(result, BaseException):
                raise result
            if not result.ok:
                self.provider_errors.append(f"{result.error_kind}")
                self.emit(EventType.warning, f"Search failed for {q.id} ({result.error_kind}); continuing", {"query_id": q.id})
                if result.error_kind == ErrorKind.auth:
                    raise ProviderError("search", ErrorKind.auth, result.error or "authentication failed")
                continue
            new = [s for hit in result.hits if (s := self._register_hit(hit, q.id, round_no))]
            self.metrics.sources_discovered = len(self.sources)
            self.emit(
                EventType.tool,
                f"search_web {q.id}: {len(result.hits)} results, {len(new)} new" + (" (cached)" if result.cached else ""),
                {
                    "tool": "search_web",
                    "query_id": q.id,
                    "query": q.text,
                    "results": len(result.hits),
                    "new_sources": len(new),
                    "cached": result.cached,
                },
            )

    def _register_hit(self, hit, query_id: str, round_no: int) -> str | None:
        try:
            validate_public_url(hit.url)
        except UnsafeURL:
            self.metrics.sources_filtered += 1
            return None
        canonical = canonicalize_url(hit.url)
        if canonical in self.by_canonical:
            existing = self.sources[self.by_canonical[canonical]]
            if query_id not in existing.query_ids:
                existing.query_ids.append(query_id)
                existing.rank_score = round(existing.rank_score + 0.05, 4)
            return None
        kind, tier = classify_source(hit.url, hit.title)
        published = parse_date(hit.published_date)
        sid = f"S{len(self.sources) + 1}"
        source = Source(
            id=sid,
            url=hit.url,
            canonical_url=canonical,
            domain=hostname(hit.url),
            title=(hit.title or hostname(hit.url))[:300],
            snippet=hit.snippet[:600],
            kind=kind,
            tier=tier,
            query_ids=[query_id],
            provider_score=hit.score,
            published_at=published.isoformat() if published else None,
            published_at_origin="provider_estimate" if published else "unknown",
            fixture=self.mode == Mode.fixture,
            round=round_no,
        )
        overlap = term_overlap(f"{source.title} {source.snippet}", self._terms())
        source.rank_score = round(0.45 * (hit.score or 0.5) + 0.35 * overlap + TIER_WEIGHT[tier], 4)
        if has_non_text_extension(hit.url):
            source.state, source.state_reason = SourceState.filtered, "Not a text document."
        elif (hit.score is not None and hit.score < 0.15) and overlap == 0:
            source.state, source.state_reason = SourceState.filtered, "Low relevance to the research criteria."
        if source.state == SourceState.filtered:
            self.metrics.sources_filtered += 1
        self.sources[sid] = source
        self.by_canonical[canonical] = sid
        return sid

    def _register_url(self, url: str, *, round_no: int, seed: bool) -> str | None:
        canonical = canonicalize_url(url)
        if canonical in self.by_canonical:
            return self.by_canonical[canonical]
        kind, tier = classify_source(url)
        sid = f"S{len(self.sources) + 1}"
        self.sources[sid] = Source(
            id=sid,
            url=url,
            canonical_url=canonical,
            domain=hostname(url),
            title=hostname(url),
            kind=kind,
            tier=tier,
            rank_score=1.0,
            fixture=self.mode == Mode.fixture,
            round=round_no,
            state_reason="Provided by the user." if seed else None,
        )
        self.by_canonical[canonical] = sid
        return sid

    def _best_per_query(self, queries: list[PlannedQuery], limit: int, *, exclude: set[str]) -> list[str]:
        chosen: list[str] = []
        per_domain = self._domain_counts(exclude)
        for q in queries:
            if len(chosen) >= limit:
                break
            found = [
                s
                for s in self.sources.values()
                if s.state == SourceState.candidate and q.id in s.query_ids and s.id not in exclude and s.id not in chosen
            ]
            found.sort(key=lambda s: s.rank_score + 0.3 * term_overlap(f"{s.title} {s.snippet}", [q.text]), reverse=True)
            for s in found:
                d = registrable_domain(s.url)
                if per_domain.get(d, 0) >= MAX_PER_DOMAIN:
                    continue
                chosen.append(s.id)
                per_domain[d] = per_domain.get(d, 0) + 1
                break
        return chosen

    def _domain_counts(self, exclude: set[str]) -> dict[str, int]:
        per_domain: dict[str, int] = {}
        for s in self.sources.values():
            if s.state in (SourceState.read, SourceState.duplicate) or s.id in exclude:
                d = registrable_domain(s.url)
                per_domain[d] = per_domain.get(d, 0) + 1
        return per_domain

    def _select_candidates(self, limit: int, *, exclude: set[str], prefer: list[str] | None = None) -> list[str]:
        if limit <= 0:
            return []
        candidates = [s for s in self.sources.values() if s.state == SourceState.candidate and s.id not in exclude]
        if prefer:
            for s in candidates:
                s.rank_score = round(s.rank_score + 0.3 * term_overlap(f"{s.title} {s.snippet}", prefer), 4)
        candidates.sort(key=lambda s: s.rank_score, reverse=True)
        per_domain = self._domain_counts(exclude)
        chosen = []
        for s in candidates:
            d = registrable_domain(s.url)
            if per_domain.get(d, 0) >= MAX_PER_DOMAIN:
                continue
            chosen.append(s.id)
            per_domain[d] = per_domain.get(d, 0) + 1
            if len(chosen) >= limit:
                break
        return chosen

    async def _read(self, sids: list[str], round_no: int) -> list[str]:
        url_to_sid = {self.sources[s].url: s for s in sids}
        result = await self.tools.read_sources([self.sources[s].url for s in sids], query=self.request.question)
        new_read: list[str] = []
        for page in result.pages:
            sid = url_to_sid.get(page.url)
            if sid and self._accept_page(sid, page.content):
                new_read.append(sid)
        for failure in result.failures:
            sid = url_to_sid.get(failure.item)
            if sid and self.sources[sid].state == SourceState.candidate:
                self.sources[sid].state = SourceState.failed
                self.sources[sid].state_reason = f"Could not be read: {failure.error[:120]}"
        unread = [s for s in sids if self.sources[s].state != SourceState.read]
        self.budget.release_pages(len(unread))
        if result.error_kind:
            self.provider_errors.append(result.error_kind)
            if not result.pages:
                self.read_errors.append(result.error_kind)
            if result.error_kind == ErrorKind.auth:
                raise ProviderError("extract", ErrorKind.auth, result.error or "authentication failed")
        failed = len(sids) - len(new_read)
        self.emit(
            EventType.tool,
            f"read_sources: {len(new_read)} of {len(sids)} pages usable" + (f", {failed} failed or skipped" if failed else ""),
            {
                "tool": "read_sources",
                "requested": len(sids),
                "read": len(new_read),
                "failures": [
                    {"source_id": s, "domain": self.sources[s].domain, "reason": self.sources[s].state_reason} for s in unread
                ],
            },
        )
        return new_read

    def _accept_page(self, sid: str, raw: str) -> bool:
        source = self.sources[sid]
        source.retrieved_at = _now()
        text = clean_content(raw)
        if looks_paywalled(text):
            source.state, source.state_reason = SourceState.failed, "Paywall or access block."
            return False
        screened, removed = screen_injection(text)
        if removed:
            source.injection_suspected = True
            self.emit(
                EventType.warning,
                f"Removed {len(removed)} instruction-like sentence{'s' if len(removed) != 1 else ''} from {source.domain} before analysis",
                {"source_id": sid},
            )
        if len(screened) < MIN_USEFUL_CHARS:
            source.state, source.state_reason = SourceState.failed, "Too little readable text."
            return False
        digest = content_hash(screened)
        if digest in self.hashes:
            source.state, source.duplicate_of = SourceState.duplicate, self.hashes[digest]
            source.state_reason = f"Same content as {self.hashes[digest]}."
            return False
        sh = shingles(screened)
        for other, other_sh in self.shingle_sets.items():
            if jaccard(sh, other_sh) >= NEAR_DUPLICATE_JACCARD:
                source.state, source.duplicate_of = SourceState.duplicate, other
                source.state_reason = f"Substantially the same content as {other}."
                return False
        if source.published_at is None and (found := find_page_date(screened)):
            source.published_at, source.published_at_origin = found.isoformat(), "page_text"
        passages = chunk_passages(sid, screened)
        if not passages:
            source.state, source.state_reason = SourceState.failed, "No usable passages."
            return False
        source.state, source.state_reason = (
            SourceState.read,
            source.state_reason if source.state_reason == "Provided by the user." else None,
        )
        source.content_hash, source.content_chars = digest, len(screened)
        if source.title == source.domain:
            first_line = screened.split("\n", 1)[0].strip()
            if 5 <= len(first_line) <= 200:
                source.title = first_line
        self.hashes[digest] = sid
        self.shingle_sets[sid] = sh
        self.passages[sid] = passages
        for p in passages:
            self.passage_index[p.id] = p
        return True

    async def _extract_round(self, sids: list[str], round_no: int) -> int:
        if not sids:
            return 0
        assert self.plan is not None
        async with self._stage(Stage.extract, f"Extracting evidence from {len(sids)} source{'s' if len(sids) != 1 else ''}"):
            terms = self._terms()
            per_source = 4 if len(sids) <= 5 else 3
            offered: dict[str, Passage] = {}
            blocks = []
            payload_passages = []
            for sid in sids:
                src = self.sources[sid]
                chosen = select_passages(self.passages[sid], [*terms, src.title], per_source)
                inner = []
                for p in chosen:
                    offered[p.id] = p
                    inner.append(f'<untrusted_passage id="{p.id}">\n{fence(p.text)}\n</untrusted_passage>')
                    payload_passages.append({"id": p.id, "source_id": sid, "text": p.text})
                published = src.published_at or "unknown"
                blocks.append(
                    f'<untrusted_source id="{sid}" domain="{attr(src.domain)}" title="{attr(src.title)}" published="{published}">\n'
                    + "\n".join(inner)
                    + "\n</untrusted_source>"
                )
            criteria = [{"id": c.id, "description": c.description, "kind": c.kind.value} for c in self.plan.criteria]
            entities = self._known_entities()
            input_text = render_sections(
                [
                    ("question", fence(self.request.question)),
                    ("criteria", dump(criteria)),
                    ("entities", dump(entities)),
                    ("passages", "\n".join(blocks)),
                ]
            )
            s = spec(Task.extract, max_output_tokens=self.settings.max_output_tokens)
            try:
                data = await self.models.call(
                    s,
                    input_text,
                    {
                        "question": self.request.question,
                        "criteria": [c.model_dump() for c in self.plan.criteria],
                        "entities": entities,
                        "passages": payload_passages,
                    },
                )
            except ProviderError as exc:
                self.emit(
                    EventType.warning, f"Evidence extraction failed ({exc.kind}); sources from this round were not analyzed"
                )
                self.notes.append(f"Evidence extraction failed in round {round_no} ({exc.kind}).")
                if exc.kind in (ErrorKind.auth, ErrorKind.quota):
                    raise
                return 0
            batch = validate_evidence(
                data.get("evidence") or [],
                passages=offered,
                sources=self.sources,
                criteria={c.id: c for c in self.plan.criteria},
                existing=self.evidence,
                known_entities=self.plan.candidate_entities,
                round_no=round_no,
            )
            self.evidence += batch.accepted
            self.metrics.evidence_accepted = len(self.evidence)
            self.metrics.evidence_rejected += len(batch.rejected)
            reasons: dict[str, int] = {}
            for r in batch.rejected:
                reasons[r.reason] = reasons.get(r.reason, 0) + 1
            self.emit(
                EventType.tool,
                f"Accepted {len(batch.accepted)} evidence item{'s' if len(batch.accepted) != 1 else ''}"
                + (f", rejected {len(batch.rejected)}" if batch.rejected else ""),
                {"accepted": len(batch.accepted), "rejected": reasons},
            )
            return len(batch.accepted)

    def _known_entities(self) -> list[str]:
        assert self.plan is not None
        names = list(self.plan.candidate_entities)
        for e in self.evidence:
            if e.entity and e.entity not in names:
                names.append(e.entity)
        return names[:20]

    def _coverage(self, extra_conflicts: list[Conflict] | None = None) -> list[CriterionCoverage]:
        assert self.plan is not None
        return compute_coverage(self.plan, self.evidence, self.sources, today=self.today, extra_conflicts=extra_conflicts)

    def _coverage_message(self) -> str:
        supported = sum(1 for c in self.coverage if c.status == CoverageStatus.supported)
        return f"Coverage: {supported} of {len(self.coverage)} criteria supported"

    def _coverage_event(self) -> dict[str, Any]:
        return {
            "coverage": [
                {"criterion_id": c.criterion_id, "status": c.status.value, "evidence": len(c.evidence_ids), "note": c.note}
                for c in self.coverage
            ]
        }

    # ------------------------------------------------------------------
    # Follow-up

    async def _follow_up(self, next_round: int) -> tuple[list[PlannedQuery], list[str]]:
        assert self.plan is not None
        gaps = gap_criteria(self.coverage)
        gap_ids = {g.criterion_id for g in gaps}
        candidates = [s for s in self.sources.values() if s.state == SourceState.candidate]
        candidates.sort(key=lambda s: s.rank_score, reverse=True)
        candidates = candidates[:12]
        actions: list[dict[str, Any]] = []
        s = spec(
            Task.follow_up, max_actions=self.settings.max_queries_per_round, max_output_tokens=self.settings.max_output_tokens
        )
        input_text = render_sections(
            [
                ("question", fence(self.request.question)),
                (
                    "gaps",
                    dump(
                        [
                            {
                                "criterion_id": g.criterion_id,
                                "description": g.description,
                                "status": g.status.value,
                                "note": g.note,
                            }
                            for g in gaps
                        ]
                    ),
                ),
                ("previous_queries", dump([q.text for q in self.queries])),
                ("entities", dump(self._known_entities())),
                (
                    "candidates",
                    "\n".join(
                        f'<untrusted_source id="{c.id}" domain="{attr(c.domain)}" title="{attr(c.title)}">{fence(c.snippet[:300])}</untrusted_source>'
                        for c in candidates
                    )
                    or "none",
                ),
            ]
        )
        # Keep enough model attempts for follow-up extraction, synthesis, and verification.
        if self.budget.attempts_left() >= 4 and self.models.can_afford(s, input_text):
            try:
                data = await self.models.call(
                    s,
                    input_text,
                    {
                        "gaps": [g.model_dump() for g in gaps],
                        "previous_queries": [q.text for q in self.queries],
                        "candidates": [c.model_dump(mode="json") for c in candidates],
                        "entities": self._known_entities(),
                    },
                )
                if data.get("stop") and not data.get("actions"):
                    self.notes.append(
                        "Follow-up stopped: " + str(data.get("stop_reason") or "remaining gaps unlikely to be resolved")[:200]
                    )
                    return [], []
                actions = list(data.get("actions") or [])
            except ProviderError as exc:
                self.emit(EventType.warning, f"Follow-up planning failed ({exc.kind}); using rule-based follow-up")
                actions = []
        if not actions:
            actions = self._fallback_actions(gaps)
        queries, reads = self._validate_actions(actions, gap_ids, {c.id for c in candidates}, next_round)
        queries = self._cover_untargeted_gaps(gaps, queries, reads, next_round)
        self.emit(
            EventType.plan,
            f"Follow-up: {len(queries)} search{'es' if len(queries) != 1 else ''}, {len(reads)} source read{'s' if len(reads) != 1 else ''} for {len(gaps)} gap{'s' if len(gaps) != 1 else ''}",
            {"queries": [{"id": q.id, "text": q.text, "criterion_ids": q.criterion_ids} for q in queries], "reads": reads},
        )
        return queries, reads

    def _gap_query(self, gap: CriterionCoverage) -> str:
        """A verification query for one gap: the first entity it is missing for, plus the criterion's terms."""
        assert self.plan is not None
        c = next(x for x in self.plan.criteria if x.id == gap.criterion_id)
        subject = gap.missing_entities[0] if gap.missing_entities else ""
        if not subject and gap.stale_entities:
            subject = gap.stale_entities[0]
        if not subject and self.plan.candidate_entities:
            subject = " ".join(self.plan.candidate_entities[:2])
        terms = " ".join(c.key_terms[:4]) or c.description
        return f"{subject} {terms}".strip()[:200]

    def _fallback_actions(self, gaps: list[CriterionCoverage]) -> list[dict[str, Any]]:
        """Rule-based follow-up used when the model is unavailable or the budget is tight."""
        ordered = sorted(gaps, key=lambda g: (not g.required, g.status != CoverageStatus.missing))
        return [
            {
                "tool": "search_web",
                "query": self._gap_query(gap),
                "topic": "general",
                "source_ids": [],
                "criterion_ids": [gap.criterion_id],
                "reason": "rule-based gap query",
            }
            for gap in ordered[: self.settings.max_queries_per_round]
        ]

    def _cover_untargeted_gaps(
        self, gaps: list[CriterionCoverage], queries: list[PlannedQuery], reads: list[str], next_round: int
    ) -> list[PlannedQuery]:
        """A required gap with no evidence at all gets a search even if the model spent its actions elsewhere.

        Seen live: the model chose to read benchmark candidates while the licensing criterion, which no
        candidate addressed, stayed missing. Reads cannot close a gap no candidate covers.
        """
        targeted = {cid for q in queries for cid in q.criterion_ids}
        if reads:
            for sid in reads:
                targeted.update(self.sources[sid].query_ids and self._criteria_of_queries(self.sources[sid].query_ids))
        previous = [set(tokenize(q.text)) for q in [*self.queries, *queries]]
        for gap in gaps:
            if len(queries) >= self.settings.max_queries_per_round:
                break
            if not gap.required or gap.status != CoverageStatus.missing or gap.criterion_id in targeted:
                continue
            text = self._gap_query(gap)
            words = set(tokenize(text))
            if len(text) < 2 or any(words and len(words & p) / max(1, len(words | p)) >= 0.8 for p in previous):
                continue
            previous.append(words)
            queries.append(
                PlannedQuery(
                    id=f"Q{len(self.queries) + len(queries) + 1}",
                    text=text,
                    purpose="search for a required criterion that no action targeted",
                    criterion_ids=[gap.criterion_id],
                    round=next_round,
                )
            )
            targeted.add(gap.criterion_id)
        return queries

    def _criteria_of_queries(self, query_ids: list[str]) -> set[str]:
        return {cid for q in self.queries if q.id in query_ids for cid in q.criterion_ids}

    def _validate_actions(
        self, actions: list[dict[str, Any]], gap_ids: set[str], candidate_ids: set[str], next_round: int
    ) -> tuple[list[PlannedQuery], list[str]]:
        previous = [set(tokenize(q.text)) for q in self.queries]
        queries: list[PlannedQuery] = []
        reads: list[str] = []
        for action in actions[: self.settings.max_queries_per_round]:
            crit_ids = [c for c in (action.get("criterion_ids") or []) if c in gap_ids] or sorted(gap_ids)[:2]
            if action.get("tool") == "read_sources":
                reads += [sid for sid in action.get("source_ids") or [] if sid in candidate_ids and sid not in reads]
            elif action.get("tool") == "search_web":
                text = " ".join(str(action.get("query") or "").split())[:240]
                if len(text) < 2:
                    continue
                words = set(tokenize(text))
                if any(words and len(words & p) / max(1, len(words | p)) >= 0.8 for p in previous):
                    continue  # near-repeat of an earlier query
                previous.append(words)
                topic = action.get("topic") if action.get("topic") in ("general", "news") else "general"
                queries.append(
                    PlannedQuery(
                        id=f"Q{len(self.queries) + len(queries) + 1}",
                        text=text,
                        purpose=str(action.get("reason") or "follow-up")[:200],
                        criterion_ids=crit_ids,
                        round=next_round,
                        topic=topic,
                    )
                )
        return queries, reads

    # ------------------------------------------------------------------
    # Synthesis, verification, repair, finalization

    async def _conclude(self) -> ResearchReport:
        assert self.plan is not None
        self.coverage = self._coverage()
        if not self.evidence:
            # No evidence can mean two different things: the research ran and found nothing usable
            # (insufficient evidence), or the run was cut off by a provider or a limit before it could
            # look (failed). The second must never be reported as the first.
            if self.stop_reason in CUT_OFF_STOP_REASONS:
                detail = self.stop_detail or self.stop_reason.value.replace("_", " ")
                return self._evidence_only_report(
                    RunStatus.failed,
                    synth_note=f"The run stopped before any evidence could be extracted ({detail.rstrip('.')}), so no answer was synthesized.",
                )
            if not any(s.state == SourceState.read for s in self.sources.values()):
                failed = sum(1 for s in self.sources.values() if s.state == SourceState.failed)
                self.stop_reason = StopReason.no_relevant_sources
                self.stop_detail = (
                    f"None of the selected pages could be read ({failed} failed)." if failed else self.stop_detail
                ) or "Search returned no usable sources."
            else:
                self.stop_reason = self.stop_reason or StopReason.no_relevant_sources
            return self._evidence_only_report(
                RunStatus.insufficient_evidence, synth_note="No usable evidence was found, so no answer was synthesized."
            )

        try:
            async with self._stage(Stage.synthesize, "Synthesizing the report from accepted evidence"):
                draft = await self._synthesize()
        except (ProviderError, BudgetExhausted, DeadlineReached) as exc:
            detail = _exc_text(exc)
            self.emit(EventType.warning, f"Synthesis failed ({detail}); reporting extracted evidence only")
            # Overrides a research-phase reason such as criteria_satisfied: the outcome is set by this failure.
            self.stop_reason, self.stop_detail = _stop_for(exc), f"Synthesis could not complete ({detail})."
            return self._evidence_only_report(
                RunStatus.partial,
                synth_note=f"Synthesis did not run ({detail}); findings below are extracted evidence, not a synthesized answer.",
            )

        evidence_ids = {e.id for e in self.evidence}
        refs = enumerate_claims(draft)
        invalid_refs = check_references(refs, evidence_ids)
        draft.conflicts = keep_valid_conflicts(draft.conflicts, evidence_ids)
        verification = VerificationSummary(invalid_references_removed=invalid_refs)
        verification_ran = False
        async with self._stage(Stage.verify, f"Verifying {len(refs)} claims against their evidence"):
            try:
                await self._verify(refs, [r for r in refs if r.claim.verdict != SupportVerdict.not_supported])
                verification_ran = True
            except (ProviderError, BudgetExhausted, DeadlineReached) as exc:
                verification.note = f"Verification did not run ({_exc_text(exc)})."
                self.emit(EventType.warning, f"Verification failed ({_exc_text(exc)}); claims are marked unverified")
                for ref in refs:
                    if ref.claim.verdict == SupportVerdict.unchecked:
                        apply_verdict(ref, SupportVerdict.unchecked, None)
            for ref in refs:
                if ref.claim.verdict == SupportVerdict.not_supported and ref.target.disposition != ClaimDisposition.removed:
                    apply_verdict(ref, SupportVerdict.not_supported, ref.claim.issue)

        failing = [r for r in refs if r.claim.verdict in (SupportVerdict.not_supported, SupportVerdict.partially_supported)]
        if verification_ran and failing and self.settings.max_repair_cycles > 0:
            verification.repair_attempted = True
            async with self._stage(
                Stage.repair, f"Repairing {len(failing)} claim{'s' if len(failing) != 1 else ''} that failed verification"
            ):
                await self._repair(failing)

        async with self._stage(Stage.finalize, "Finalizing report"):
            removed = finalize_draft(draft, [c.id for c in self.plan.criteria if c.kind == CriterionKind.eligibility])
            verification.removed_claims = removed[:20]
            verification.claims_checked = len(refs)
            for ref in refs:
                v = ref.claim.verdict
                if v == SupportVerdict.supported:
                    verification.supported += 1
                elif v == SupportVerdict.partially_supported:
                    verification.partially_supported += 1
                elif v == SupportVerdict.not_supported:
                    verification.not_supported += 1
                else:
                    verification.unchecked += 1
            conflicts = self._merge_conflicts(draft.conflicts)
            self.coverage = self._coverage(extra_conflicts=[c for c in conflicts if not c.resolution])
            unchecked = any(r.claim.verdict == SupportVerdict.unchecked for r in refs)
            status = decide_status(
                coverage=self.coverage,
                refs=refs,
                verification_ran=verification_ran,
                evidence_count=len(self.evidence),
                hit_limit=unchecked,
            )
            if status == RunStatus.completed:
                self.stop_reason = (
                    self.stop_reason if self.stop_reason == StopReason.criteria_satisfied else StopReason.criteria_satisfied
                )
                self.stop_detail = self.stop_detail or "All required criteria have supporting evidence."
            return self._build_report(status, draft, refs, verification, conflicts, verification_ran)

    async def _synthesize(self) -> Draft:
        assert self.plan is not None
        evidence_rows = [self._evidence_row(e) for e in self.evidence]
        coverage_rows = [
            {
                "criterion_id": c.criterion_id,
                "description": c.description,
                "kind": c.kind.value,
                "required": c.required,
                "status": c.status.value,
                "note": c.note,
            }
            for c in self.coverage
        ]
        context = {
            "question": self.request.question,
            "interpretation": self.plan.interpretation,
            "task_type": self.plan.task_type.value,
            "target_entity_count": self.plan.target_entity_count,
            "candidate_entities": self.plan.candidate_entities,
            "assumptions": self.plan.assumptions,
            "today": self.today.isoformat(),
        }
        input_text = render_sections(
            [
                ("context", fence(dump(context))),
                ("criteria_coverage", fence(dump(coverage_rows))),
                ("evidence", fence(dump(evidence_rows))),
            ]
        )
        s = spec(Task.synthesize, max_output_tokens=self.settings.max_output_tokens)
        data = await self.models.call(
            s,
            input_text,
            {"context": context, "coverage": coverage_rows, "evidence": evidence_rows, "plan": self.plan.model_dump(mode="json")},
            finalizing=True,
        )
        return parse_draft(data, self.plan)

    def _evidence_row(self, e: Evidence) -> dict[str, Any]:
        src = self.sources[e.source_id]
        return {
            "id": e.id,
            "claim": e.claim,
            "quote": e.quote,
            "criterion_ids": e.criterion_ids,
            "entity": e.entity,
            "polarity": e.polarity,
            "first_party": e.first_party,
            "source_id": src.id,
            "domain": src.domain,
            "source_kind": src.kind.value,
            "tier": src.tier.value,
            "published": src.published_at,
        }

    def _verification_input(self, refs: list[ClaimRef]) -> tuple[str, dict[str, Any]]:
        cited = {eid for r in refs for eid in r.target.evidence_ids}
        by_id = {e.id: e for e in self.evidence}
        evidence = {}
        for eid in sorted(cited, key=lambda x: int(x[1:])):
            e = by_id[eid]
            passage = self.passage_index.get(e.passage_id)
            evidence[eid] = {
                "quote": e.quote,
                "domain": self.sources[e.source_id].domain,
                "first_party": e.first_party,
                "passage": passage.text[:900] if passage else "",
            }
        claims = [
            {"id": r.claim.id, "kind": r.claim.kind.value, "text": r.target.text, "evidence_ids": r.target.evidence_ids}
            for r in refs
        ]
        input_text = render_sections(
            [
                ("claims", fence(dump(claims))),
                (
                    "evidence",
                    "\n".join(
                        f'<untrusted_passage id="{eid}" domain="{attr(v["domain"])}" first_party="{str(v["first_party"]).lower()}">\n'
                        f"QUOTE: {fence(v['quote'])}\nCONTEXT: {fence(v['passage'])}\n</untrusted_passage>"
                        for eid, v in evidence.items()
                    ),
                ),
            ]
        )
        return input_text, {"claims": claims, "evidence": evidence}

    async def _verify(self, all_refs: list[ClaimRef], refs: list[ClaimRef]) -> None:
        if not refs:
            return
        input_text, payload = self._verification_input(refs)
        s = spec(Task.verify, max_output_tokens=self.settings.max_output_tokens)
        data = await self.models.call(s, input_text, payload, finalizing=True)
        by_id = {r.claim.id: r for r in refs}
        seen = set()
        for item in data.get("verdicts") or []:
            ref = by_id.get(item.get("claim_id"))
            if ref is None or ref.claim.id in seen:
                continue
            seen.add(ref.claim.id)
            try:
                verdict = SupportVerdict(item.get("verdict"))
            except ValueError:
                continue
            apply_verdict(ref, verdict, (str(item.get("issue"))[:300] if item.get("issue") else None))
        for ref in refs:
            if ref.claim.id not in seen:
                apply_verdict(ref, SupportVerdict.unchecked, None)
        self.emit(
            EventType.tool,
            f"Verified {len(refs)} claims",
            {"verdicts": {v.value: sum(1 for r in all_refs if r.claim.verdict == v) for v in SupportVerdict}},
        )

    async def _repair(self, failing: list[ClaimRef]) -> None:
        """One repair cycle: rewrite or remove failing claims, then re-verify rewrites.

        A rewrite only replaces the original when re-verification supports it.
        """
        s = spec(Task.repair, max_output_tokens=self.settings.max_output_tokens)
        claims = [
            {
                "id": r.claim.id,
                "text": r.target.text,
                "issue": r.claim.issue,
                "verdict": r.claim.verdict.value,
                "evidence_ids": r.target.evidence_ids,
            }
            for r in failing
        ]
        evidence_rows = [
            {"id": e.id, "claim": e.claim, "quote": e.quote, "entity": e.entity, "first_party": e.first_party}
            for e in self.evidence
        ]
        input_text = render_sections([("failed_claims", fence(dump(claims))), ("evidence", fence(dump(evidence_rows)))])
        verify_reserve = spec(Task.verify, max_output_tokens=self.settings.max_output_tokens)
        if not (self.models.can_afford(s, input_text) and self.budget.attempts_left() >= 2):
            self.notes.append("Claims that failed verification were not repaired because the run budget was exhausted.")
            return
        try:
            data = await self.models.call(s, input_text, {"claims": claims, "evidence": evidence_rows}, finalizing=True)
        except (ProviderError, BudgetExhausted, DeadlineReached) as exc:
            self.notes.append(f"Repair did not run ({_exc_text(exc)}).")
            return
        by_id = {r.claim.id: r for r in failing}
        valid_ids = {e.id for e in self.evidence}
        originals: dict[str, tuple[str, list[str], SupportVerdict, str | None]] = {}
        rewritten: list[ClaimRef] = []
        for item in data.get("repairs") or []:
            ref = by_id.get(item.get("claim_id"))
            if ref is None or ref.claim.id in originals:
                continue
            text = " ".join(str(item.get("text") or "").split())[:1_200]
            ids = [e for e in dict.fromkeys(item.get("evidence_ids") or []) if e in valid_ids]
            if item.get("action") != "rewrite" or not text or not ids:
                continue
            originals[ref.claim.id] = (ref.target.text, list(ref.target.evidence_ids), ref.claim.verdict, ref.claim.issue)
            ref.target.text, ref.target.evidence_ids = text, ids
            ref.claim.text, ref.claim.evidence_ids, ref.claim.repaired = text, ids, True
            rewritten.append(ref)
        if not rewritten:
            return
        input_text, _ = self._verification_input(rewritten)
        if not self.models.can_afford(verify_reserve, input_text):
            self._restore(rewritten, originals)
            self.notes.append(
                "Repaired claims could not be re-verified within the budget, so the originals were kept as checked."
            )
            return
        try:
            await self._verify(rewritten, rewritten)
        except (ProviderError, BudgetExhausted, DeadlineReached) as exc:
            self._restore(rewritten, originals)
            self.notes.append(f"Repaired claims could not be re-verified ({_exc_text(exc)}).")
            return
        self._restore(
            [r for r in rewritten if r.claim.verdict in (SupportVerdict.not_supported, SupportVerdict.unchecked)], originals
        )

    @staticmethod
    def _restore(refs: list[ClaimRef], originals: dict[str, tuple[str, list[str], SupportVerdict, str | None]]) -> None:
        for ref in refs:
            text, ids, verdict, issue = originals[ref.claim.id]
            ref.target.text, ref.target.evidence_ids = text, ids
            ref.claim.text, ref.claim.evidence_ids, ref.claim.repaired = text, ids, False
            apply_verdict(ref, verdict, issue)

    def _polarity_conflicts(self) -> list[Conflict]:
        criteria = {c.id: c for c in self.plan.criteria} if self.plan else {}
        return polarity_conflicts(self.evidence, self.sources, criteria)

    def _merge_conflicts(self, model_conflicts: list[Conflict]) -> list[Conflict]:
        """Model-described conflicts first; code-detected ones (flagged for review) fill in what the model missed."""
        conflicts = list(model_conflicts)
        covered = {(tuple(c.criterion_ids), c.entity) for c in conflicts}
        for c in self._polarity_conflicts():
            if (tuple(c.criterion_ids), c.entity) not in covered:
                conflicts.append(c)
        return conflicts[:10]

    # ------------------------------------------------------------------
    # Report assembly

    def _limitations(self, model_limitations: list[str], verification_ran: bool) -> list[str]:
        out: list[str] = []
        if self.mode == Mode.fixture:
            out.append("Fixture mode: sources and model outputs are synthetic test data, not live research.")
        if self.stop_reason and self.stop_reason not in (StopReason.criteria_satisfied,):
            out.append(f"Research stopped early: {self.stop_detail or self.stop_reason.value}")
        for c in self.coverage:
            if c.required and c.status != CoverageStatus.supported:
                out.append(f"{c.criterion_id} ({c.description}): {c.status.value}. {c.note or ''}".strip())
        failed = [s for s in self.sources.values() if s.state == SourceState.failed]
        if failed:
            out.append(
                f"{len(failed)} source{'s' if len(failed) != 1 else ''} could not be read (blocked, paywalled, or failed extraction)."
            )
        if any(s.injection_suspected for s in self.sources.values()):
            out.append("Some pages contained instruction-like text that was removed before analysis.")
        if any(c.needs_freshness for c in (self.plan.criteria if self.plan else [])):
            out.append("Publication dates are provider estimates or dates found in page text and may be inaccurate.")
        if not verification_ran:
            out.append("Claims were not independently verified against their evidence.")
        out += self.notes
        out += model_limitations
        return list(dict.fromkeys(x for x in out if x))[:12]

    def _next_steps(self, model_steps: list[str]) -> list[str]:
        out = list(model_steps)
        for c in self.coverage:
            if c.required and c.status in (CoverageStatus.missing, CoverageStatus.weak, CoverageStatus.stale):
                out.append(f"Find primary or independent sources for: {c.description}.")
        return list(dict.fromkeys(out))[:6]

    def _execution(self) -> ExecutionInfo:
        m = self.metrics
        m.finished_at = _now()
        m.duration_ms = round((time.perf_counter() - self._started_perf) * 1000, 1)
        m.input_tokens, m.output_tokens = self.budget.input_tokens, self.budget.output_tokens
        m.estimated_cost_usd = round(self.budget.spent_usd, 5)
        m.cost_uncertain = self.budget.cost_uncertain
        m.sources_discovered = len(self.sources)
        m.evidence_accepted = len(self.evidence)
        s = self.settings
        return ExecutionInfo(
            mode=self.mode,
            model=self.model_name,
            sdk_version=self.sdk_version,
            prompt_version=PROMPT_VERSION,
            reasoning_effort=s.reasoning_effort if self.mode == Mode.live else None,
            limits={
                "max_rounds": self.max_rounds,
                "max_queries_per_round": s.max_queries_per_round,
                "max_pages_per_run": s.max_pages_per_run,
                "max_concurrency": s.max_concurrency,
                "max_model_attempts": s.max_model_attempts,
                "max_repair_cycles": s.max_repair_cycles,
                "run_deadline_s": s.run_deadline_s,
                "finalize_reserve_s": s.finalize_reserve_s,
                "max_tokens_per_run": s.max_tokens_per_run,
                "max_cost_usd_per_run": s.max_cost_usd_per_run,
            },
            metrics=m,
        )

    def _sources_for_report(self) -> list[Source]:
        cited = {e.source_id for e in self.evidence}
        order = {
            SourceState.read: 0,
            SourceState.failed: 1,
            SourceState.duplicate: 2,
            SourceState.candidate: 3,
            SourceState.filtered: 4,
        }
        return sorted(self.sources.values(), key=lambda s: (s.id not in cited, order[s.state], int(s.id[1:])))

    def _build_report(
        self,
        status: RunStatus,
        draft: Draft,
        refs: list[ClaimRef],
        verification: VerificationSummary,
        conflicts: list[Conflict],
        verification_ran: bool,
    ) -> ResearchReport:
        assert self.plan is not None
        confidence = assess_confidence(
            status=status,
            coverage=self.coverage,
            refs=refs,
            evidence=self.evidence,
            sources=self.sources,
            conflicts=conflicts,
            verification_ran=verification_ran,
            criteria=self.plan.criteria,
        )
        return ResearchReport(
            run_id=self.run_id,
            question=self.request.question,
            status=status,
            stop_reason=self.stop_reason,
            stop_detail=self.stop_detail,
            mode=self.mode,
            short_answer=draft.short_answer,
            key_findings=draft.findings,
            comparison=draft.comparison,
            entities=draft.entities,
            sources=self._sources_for_report(),
            evidence=self.evidence,
            coverage=self.coverage,
            unresolved_criteria=[c.criterion_id for c in self.coverage if c.required and c.status != CoverageStatus.supported],
            conflicts=conflicts,
            confidence=confidence,
            limitations=self._limitations(draft.limitations, verification_ran),
            assumptions=self.plan.assumptions + ([self.plan.ambiguity_note] if self.plan.ambiguity_note else []),
            next_steps=self._next_steps(draft.next_steps),
            plan=self.plan,
            claims=[r.claim for r in refs],
            verification=verification,
            execution=self._execution(),
            created_at=_now(),
        )

    def _evidence_only_report(self, status: RunStatus, *, synth_note: str) -> ResearchReport:
        """Deterministic report from collected evidence, used when synthesis cannot run."""
        plan = self.plan
        findings: list[Finding] = []
        if plan is not None:
            for crit in plan.criteria:
                ev = [e for e in self.evidence if crit.id in e.criterion_ids and e.polarity == "supports"]
                ev.sort(
                    key=lambda e: (
                        e.first_party,
                        {SourceTier.high: 0, SourceTier.medium: 1, SourceTier.low: 2}[self.sources[e.source_id].tier],
                    )
                )
                for e in ev[:2]:
                    findings.append(
                        Finding(
                            text=e.claim,
                            kind=ClaimKind.fact,
                            criterion_ids=[crit.id],
                            evidence_ids=[e.id],
                            verdict=SupportVerdict.unchecked,
                            disposition=ClaimDisposition.qualified,
                            note="Restated from a single quoted passage; not synthesized or verified.",
                        )
                    )
        findings = findings[:10]
        if self.evidence:
            answer = f"{synth_note} {len(self.evidence)} evidence item{'s' if len(self.evidence) != 1 else ''} from {len({e.source_id for e in self.evidence})} source(s) are listed below with their quotes."
        else:
            answer = synth_note
        verification = VerificationSummary(note="Verification did not run.")
        coverage = self._coverage() if plan else []
        self.coverage = coverage
        confidence = assess_confidence(
            status=status,
            coverage=coverage,
            refs=[],
            evidence=self.evidence,
            sources=self.sources,
            conflicts=[],
            verification_ran=False,
            criteria=plan.criteria if plan else None,
        )
        return ResearchReport(
            run_id=self.run_id,
            question=self.request.question,
            status=status,
            stop_reason=self.stop_reason,
            stop_detail=self.stop_detail,
            mode=self.mode,
            short_answer=CheckedText(text=answer, disposition=ClaimDisposition.qualified, verdict=SupportVerdict.unchecked),
            key_findings=findings,
            sources=self._sources_for_report(),
            evidence=self.evidence,
            coverage=coverage,
            unresolved_criteria=[c.criterion_id for c in coverage if c.required and c.status != CoverageStatus.supported],
            conflicts=self._polarity_conflicts(),
            confidence=confidence,
            limitations=self._limitations([], False),
            assumptions=(plan.assumptions if plan else []),
            next_steps=self._next_steps([]) or ["Retry the run, or rephrase the question with more specific terms."],
            plan=plan,
            claims=[],
            verification=verification,
            execution=self._execution(),
            created_at=_now(),
        )

    def _failure_report(self, exc: BaseException, *, during: str) -> ResearchReport:
        self._stop(_stop_for(exc), f"Failed during {during}: {_exc_text(exc)}.")
        self.emit(EventType.error, f"Run failed during {during} ({_exc_text(exc)})")
        return self._evidence_only_report(RunStatus.failed, synth_note=f"The run failed during {during} ({_exc_text(exc)}).")

    def snapshot_report(self, status: RunStatus, reason: StopReason, detail: str) -> ResearchReport:
        """Report from current state without further provider calls (cancellation, interruption, hard timeout)."""
        self.stop_reason, self.stop_detail = reason, detail
        note = {
            RunStatus.cancelled: "The run was cancelled before it finished.",
            RunStatus.interrupted: "The run was interrupted before it finished.",
        }.get(status, detail)
        return self._evidence_only_report(status, synth_note=note)


# ---------------------------------------------------------------------------
# Helpers


def _exc_text(exc: BaseException) -> str:
    if isinstance(exc, ProviderError):
        return f"{exc.provider} {exc.kind}"
    if isinstance(exc, BudgetExhausted):
        return f"{exc.resource} budget exhausted"
    if isinstance(exc, DeadlineReached):
        return "deadline reached"
    return type(exc).__name__


def _stop_for(exc: BaseException) -> StopReason:
    if isinstance(exc, BudgetExhausted):
        return StopReason.budget_exhausted
    if isinstance(exc, DeadlineReached):
        return StopReason.deadline_reached
    if isinstance(exc, ProviderError):
        if exc.kind == ErrorKind.auth:
            return StopReason.provider_auth_error
        if exc.kind in (ErrorKind.malformed_response, ErrorKind.refusal, ErrorKind.incomplete):
            return StopReason.model_output_invalid
        return StopReason.provider_unavailable
    return StopReason.internal_error


def normalize_plan(data: dict[str, Any], *, question: str, max_queries: int) -> ResearchPlan:
    """Validate the model's plan and assign application ids (K#, Q#)."""

    def text(value: Any, limit: int) -> str:
        return " ".join(str(value or "").split())[:limit]

    def texts(values: Any, n: int, limit: int) -> list[str]:
        return [t for t in (text(v, limit) for v in (values or [])[:n]) if t]

    try:
        task_type = TaskType(data.get("task_type"))
    except ValueError:
        task_type = TaskType.explainer
    criteria: list[Criterion] = []
    id_map: dict[str, list[str]] = {}  # planner id -> application ids (several when a criterion was split into parts)
    for raw in (data.get("criteria") or [])[:6]:
        desc = text(raw.get("description"), 300)
        if not desc:
            continue
        try:
            kind = CriterionKind(raw.get("kind"))
        except ValueError:
            kind = CriterionKind.general
        parts = texts(raw.get("parts"), MAX_CRITERION_PARTS, 120)
        # A compound requirement becomes one criterion per part; each part is tracked and reported on its own.
        pieces = [(f"{desc}: {part}", desc) for part in parts] if len(parts) >= 2 else [(desc, None)]
        planner_id = str(raw.get("id") or f"K{len(criteria) + 1}")
        for description, group in pieces:
            if len(criteria) >= MAX_CRITERIA:
                break
            cid = f"K{len(criteria) + 1}"
            id_map.setdefault(planner_id, []).append(cid)
            criteria.append(
                Criterion(
                    id=cid,
                    description=description,
                    kind=kind,
                    required=bool(raw.get("required", True)),
                    needs_freshness=bool(raw.get("needs_freshness")),
                    comparative=bool(raw.get("comparative")),
                    key_terms=texts(raw.get("key_terms"), 6, 40),
                    group=group,
                )
            )
    if not criteria:
        criteria = [Criterion(id="K1", description=text(question, 300), kind=CriterionKind.general, required=True)]
    if not any(c.required for c in criteria):
        # A plan with nothing required would count as satisfied with no evidence at all; every criterion is required instead.
        criteria = [c.model_copy(update={"required": True}) for c in criteria]
    queries: list[PlannedQuery] = []
    seen: set[str] = set()
    for raw in data.get("queries") or []:
        q = text(raw.get("text"), 240)
        if len(q) < 2 or q.casefold() in seen:
            continue
        seen.add(q.casefold())
        crit_ids = [cid for c in raw.get("criterion_ids") or [] for cid in id_map.get(c, [])]
        queries.append(
            PlannedQuery(
                id=f"Q{len(queries) + 1}",
                text=q,
                purpose=text(raw.get("purpose"), 200),
                criterion_ids=crit_ids or [criteria[0].id],
                round=1,
                topic=raw.get("topic") if raw.get("topic") in ("general", "news") else "general",
            )
        )
        if len(queries) >= max_queries:
            break
    if not queries:
        queries = [
            PlannedQuery(
                id="Q1",
                text=text(question, 240),
                purpose="Direct search for the question",
                criterion_ids=[c.id for c in criteria],
            )
        ]
    target = data.get("target_entity_count")
    freshness = data.get("freshness_days")
    return ResearchPlan(
        objective=text(data.get("objective"), 400) or text(question, 400),
        task_type=task_type,
        interpretation=text(data.get("interpretation"), 600) or text(question, 600),
        assumptions=texts(data.get("assumptions"), 8, 300),
        constraints=texts(data.get("constraints"), 8, 300),
        ambiguity_note=text(data.get("ambiguity_note"), 400) or None,
        freshness_days=max(7, min(3650, int(freshness))) if isinstance(freshness, int) and freshness > 0 else None,
        target_entity_count=max(1, min(10, int(target))) if isinstance(target, int) and target > 0 else None,
        candidate_entities=list(dict.fromkeys(texts(data.get("candidate_entities"), 10, 80))),
        criteria=criteria,
        queries=queries,
        steps=texts(data.get("steps"), 8, 300),
    )
