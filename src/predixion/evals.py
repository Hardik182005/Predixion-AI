"""Evaluation suite: the research agent against a fixed one-pass baseline.

predixion eval --mode fixture     deterministic regression run (no network, no cost)
predixion eval --mode live        real providers, stopped before --max-spend (default $3)

Both systems answer the same questions with the same model and comparable
retrieval. The baseline runs one search for the question, reads up to
MAX_PAGES_PER_RUN results, and makes one model call that answers with quoted
citations. It has no plan, follow-up, source filtering, verification, or repair.

Scoring is model-free so the agent's verifier never grades its own output. A
claim counts as supported when its cited quotes exist in the source and contain
most of the claim's content words (`judge_support`). That is a strict lexical
proxy: it under-credits faithful paraphrase and cannot certify that a claim is
true. Representative evidence still needs a human read.

In fixture mode the baseline's "model" is scripted, like the agent's, so the
fixture comparison only shows that the harness works. Use live results to
compare the two systems.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import PROMPT_VERSION, Settings
from .contracts import (
    ClaimDisposition,
    CoverageStatus,
    Criterion,
    EligibilityStatus,
    ExecutionMetrics,
    ExtractedPage,
    FaultInjection,
    Mode,
    ResearchReport,
    ResearchRequest,
    RunStatus,
    SearchArgs,
    StopReason,
    SupportVerdict,
)
from .fixtures import FIXTURE_MODEL, FixtureExtract, FixtureModel, FixtureSearch, Scenario, judge_support, load_scenarios
from .llm import FaultyModel, ModelCaller, ModelClient, ModelOutcome, ModelRoutes
from .orchestrator import Providers, ResearchRun
from .prompts import BOOL, STR, UNTRUSTED_RULES, Task, TaskSpec, arr, attr, fence, obj, render_sections
from .reliability import Budget, BudgetExhausted, Deadline, DeadlineReached, ProviderError, RetryPolicy
from .sources import normalize_for_match, tokenize
from .tools import ToolRunner, apply_faults
from .urls import is_safe_public_url

BASELINE_PAGE_CHARS = 6_000
MIN_QUOTE_CHARS = 8
MIN_RUN_CAP_USD = 0.05  # below this, a live run would likely stop on budget, so the suite stops instead
CLIP = 300

BASELINE_INSTRUCTIONS = f"""You answer a research question in one pass using only the numbered web sources provided.

{UNTRUSTED_RULES}

If the sources do not answer the question, set answerable to false, say so briefly in answer, and return no claims.
Otherwise write a 2 to 4 sentence answer and 3 to 8 claims. Each claim cites one source number and copies a short quote (one sentence or less) exactly as it appears in that source, supporting the claim."""

BASELINE_SCHEMA = obj(
    {
        "answerable": BOOL,
        "answer": STR,
        "claims": arr(obj({"text": STR, "source": {"type": "integer"}, "quote": STR})),
    }
)


# ---------------------------------------------------------------------------
# Cases


@dataclass(frozen=True)
class EvalCase:
    id: str
    scenario: str  # fixture scenario id; its question is used in both modes
    category: str
    expected: str
    checks: tuple[str, ...]
    fault: FaultInjection | None = None

    @property
    def question(self) -> str:
        return load_scenarios()[self.scenario].question


CASES = [
    EvalCase(
        "memory_comparison",
        "agent_memory",
        "assignment_example",
        "Compares memory approaches on the planned dimensions with cited findings and a comparison table.",
        ("answers", "citations_resolve", "comparison_table"),
    ),
    EvalCase(
        "vector_db_comparison",
        "vector_databases",
        "assignment_example",
        "Compares three open-source vector databases; vendor claims stay attributed and unsupported superlatives are dropped.",
        ("answers", "citations_resolve", "comparison_table"),
    ),
    EvalCase(
        "hr_tech_discovery",
        "hr_tech_india",
        "assignment_example",
        "Lists at most five companies and includes only those whose eligibility is backed by evidence; never pads the list.",
        ("answers", "citations_resolve", "entities_not_padded", "eligibility_backed"),
    ),
    EvalCase(
        "multi_agent_pros_cons",
        "multi_agent_support",
        "assignment_example",
        "Gives cited pros and cons of multi-agent support automation.",
        ("answers", "citations_resolve"),
    ),
    EvalCase(
        "nonexistent_product",
        "nonexistent_entity",
        "nonexistent_entity",
        "Says it found no evidence for the product and makes no factual claims about it.",
        ("abstains",),
    ),
    EvalCase(
        "ambiguous_mercury",
        "ambiguous_mercury",
        "ambiguous_request",
        "States which meaning of 'mercury' it researched, then answers with citations.",
        ("ambiguity_noted", "answers", "citations_resolve"),
    ),
    EvalCase(
        "contradictory_sqlite",
        "contradictory_sqlite",
        "contradictory_evidence",
        "Reports that sources disagree instead of silently picking a side.",
        ("conflict_reported", "answers", "citations_resolve"),
    ),
    EvalCase(
        "search_provider_down",
        "agent_memory",
        "provider_failure",
        "With search unavailable (injected), fails closed: a failed report with provider_unavailable and no findings.",
        ("fails_closed",),
        FaultInjection(search="unavailable"),
    ),
]


# ---------------------------------------------------------------------------
# Results


@dataclass
class ScoredClaim:
    text: str
    verdict: str
    issue: str | None
    quotes: list[str]
    sources: list[str]


@dataclass
class SystemResult:
    system: str
    status: str
    stop_reason: str | None = None
    confidence: str | None = None
    error: str | None = None
    abstained: bool = False
    claims: list[ScoredClaim] = field(default_factory=list)
    invalid_citations: int = 0
    criteria_covered: int | None = None
    criteria_total: int | None = None
    reported_criteria_supported: int | None = None  # agent only: its own coverage table, for comparison with the lexical count
    checks: dict[str, bool | None] = field(default_factory=dict)
    latency_s: float = 0.0
    cost_usd: float = 0.0
    cost_uncertain: bool = False
    model_calls: int = 0
    model_fallbacks: int = 0
    models_used: dict[str, int] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    search_calls: int = 0
    pages_read: int = 0

    def count(self, verdict: SupportVerdict) -> int:
        return sum(1 for c in self.claims if c.verdict == verdict)


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= CLIP else text[: CLIP - 1] + "…"


def criteria_coverage(claims: list[ScoredClaim], criteria: list[Criterion]) -> tuple[int, int] | None:
    """Required criteria that a supported or partially supported claim addresses (by key-term overlap)."""
    required = [c for c in criteria if c.required]
    if not required:
        return None
    good = [set(tokenize(c.text)) for c in claims if c.verdict in (SupportVerdict.supported, SupportVerdict.partially_supported)]
    covered = 0
    for crit in required:
        terms = set(tokenize(" ".join(crit.key_terms))) or set(tokenize(crit.description))
        need = min(2, len(terms))
        if need and any(len(terms & words) >= need for words in good):
            covered += 1
    return covered, len(required)


# ---------------------------------------------------------------------------
# Agent


def _agent_checks(report: ResearchReport) -> dict[str, Any]:
    evidence_ids = {e.id for e in report.evidence}
    cited = [i for f in report.key_findings for i in f.evidence_ids] + report.short_answer.evidence_ids
    target = (report.plan.target_entity_count if report.plan else None) or 5
    return {
        "answers": report.status in (RunStatus.completed, RunStatus.partial) and bool(report.key_findings),
        "citations_resolve": all(i in evidence_ids for i in cited),
        "comparison_table": report.comparison is not None and len(report.comparison.rows) >= 2,
        "entities_not_padded": sum(e.included for e in report.entities) <= target,
        "eligibility_backed": all(
            e.eligibility and all(c.status == EligibilityStatus.met and c.evidence_ids for c in e.eligibility)
            for e in report.entities
            if e.included
        ),
        "abstains": report.status == RunStatus.insufficient_evidence or not report.key_findings,
        "ambiguity_noted": report.plan is not None and bool(report.plan.ambiguity_note),
        "conflict_reported": bool(report.conflicts) or any(c.status == CoverageStatus.conflicting for c in report.coverage),
        "fails_closed": report.status in (RunStatus.failed, RunStatus.insufficient_evidence)
        and not report.key_findings
        and report.stop_reason in (StopReason.provider_unavailable, StopReason.provider_auth_error),
    }


async def run_agent(case: EvalCase, settings: Settings, providers: Providers) -> tuple[SystemResult, ResearchReport]:
    request = ResearchRequest(question=case.question, mode=providers.mode, fault=case.fault)
    run = ResearchRun("run_" + secrets.token_hex(12), request, settings, providers, lambda *_: None)
    started = time.perf_counter()
    report = await run.execute()
    latency = time.perf_counter() - started

    evidence = {e.id: e for e in report.evidence}
    urls = {s.id: s.url for s in report.sources}
    claims, invalid = [], 0
    for f in report.key_findings:
        if f.disposition == ClaimDisposition.removed:
            continue
        cited = [evidence[i] for i in f.evidence_ids if i in evidence]
        invalid += len(f.evidence_ids) - len(cited)
        verdict, issue = judge_support(f.text, [e.quote for e in cited])
        claims.append(
            ScoredClaim(f.text, verdict, issue, [_clip(e.quote) for e in cited], [urls.get(e.source_id, "") for e in cited])
        )

    m = report.execution.metrics
    result = SystemResult(
        system="agent",
        status=report.status.value,
        stop_reason=report.stop_reason.value if report.stop_reason else None,
        confidence=report.confidence.level.value,
        error=report.stop_detail if report.status == RunStatus.failed else None,
        abstained=report.status == RunStatus.insufficient_evidence or not claims,
        claims=claims,
        invalid_citations=invalid,
        latency_s=round(latency, 2),
        cost_usd=round(m.estimated_cost_usd, 5),
        cost_uncertain=m.cost_uncertain,
        model_calls=m.model_calls,
        model_fallbacks=m.model_fallbacks,
        models_used=dict(m.models_used),
        input_tokens=m.input_tokens,
        output_tokens=m.output_tokens,
        search_calls=m.search_calls,
        pages_read=m.pages_read,
        reported_criteria_supported=sum(c.required and c.status == CoverageStatus.supported for c in report.coverage),
    )
    available = _agent_checks(report)
    result.checks = {name: available[name] for name in case.checks}
    return result, report


# ---------------------------------------------------------------------------
# One-pass baseline


class FixtureOnePass:
    """Scripted one-pass answerer for fixture mode.

    Cites every scripted fact found in the pages, plus the scenario's scripted
    bad extractions and overclaim. Those are what the agent's validation and
    verification stages catch; with no such stages here, they stay in the answer.
    """

    model = FIXTURE_MODEL
    sdk_version = None

    def __init__(self, scenario: Scenario | None) -> None:
        self.scenario = scenario

    async def generate(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, timeout: float) -> ModelOutcome:
        del spec, timeout
        claims: list[dict[str, Any]] = []
        pages = payload.get("pages") or []
        if self.scenario is not None and pages:
            for page in pages:
                text = normalize_for_match(page["text"])
                for fact in self.scenario.facts:
                    if normalize_for_match(fact["quote"]) in text:
                        claims.append({"text": fact["claim"], "source": page["index"], "quote": fact["quote"]})
            claims = claims[:6]
            for bad in self.scenario.bad_extractions:
                claims.append({"text": bad["claim"], "source": pages[0]["index"], "quote": bad["quote"]})
            over = self.scenario.synthesis.get("overclaim")
            if over and claims:
                claims.append({"text": over["text"], "source": claims[0]["source"], "quote": claims[0]["quote"]})
        claims = claims[:8]
        answer = " ".join(c["text"] for c in claims[:2]) or "The sources do not answer the question."
        data = {"answerable": bool(claims), "answer": answer, "claims": claims}
        return ModelOutcome(data=data, input_tokens=len(input_text) // 4 + 300, output_tokens=len(json.dumps(data)) // 4)


def baseline_spec(settings: Settings) -> TaskSpec:
    return TaskSpec(Task.baseline, BASELINE_INSTRUCTIONS, BASELINE_SCHEMA, min(4_000, settings.max_output_tokens))


def baseline_input(question: str, pages: list[ExtractedPage]) -> tuple[str, dict[str, Any]]:
    shown = [(i, p.url, p.content[:BASELINE_PAGE_CHARS]) for i, p in enumerate(pages, 1)]
    blocks = "\n\n".join(
        f'<untrusted_source index="{i}" url="{attr(url)}">\n{fence(text)}\n</untrusted_source>' for i, url, text in shown
    )
    input_text = render_sections([("question", fence(question)), ("sources", blocks)])
    payload = {"question": question, "pages": [{"index": i, "url": url, "text": text} for i, url, text in shown]}
    return input_text, payload


def score_baseline_claims(data: dict[str, Any], pages: list[dict[str, Any]]) -> tuple[list[ScoredClaim], int]:
    normalized = {p["index"]: normalize_for_match(p["text"]) for p in pages}
    urls = {p["index"]: p["url"] for p in pages}
    claims, invalid = [], 0
    raw = data.get("claims")
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            invalid += 1
            continue
        text, quote, source = str(item.get("text") or ""), str(item.get("quote") or ""), item.get("source")
        needle = normalize_for_match(quote)
        found = isinstance(source, int) and len(needle) >= MIN_QUOTE_CHARS and needle in normalized.get(source, "")
        if found:
            verdict, issue = judge_support(text, [quote])
        else:
            invalid += 1
            verdict, issue = SupportVerdict.not_supported, "Quote not found in the cited source."
        url = urls.get(source, "") if isinstance(source, int) else ""
        claims.append(ScoredClaim(text, verdict, issue, [_clip(quote)], [url]))
    return claims, invalid


async def run_baseline(case: EvalCase, settings: Settings, providers: Providers) -> SystemResult:
    live = providers.mode == Mode.live
    budget = Budget(
        max_model_attempts=settings.max_model_attempts,
        max_tokens=settings.max_tokens_per_run,
        max_cost_usd=settings.max_cost_usd_per_run,
        max_pages=settings.max_pages_per_run,
        input_usd_per_mtok=settings.model_input_usd_per_mtok if live else 0.0,
        output_usd_per_mtok=settings.model_output_usd_per_mtok if live else 0.0,
        usd_per_credit=settings.tavily_usd_per_credit if live else 0.0,
    )
    deadline = Deadline(settings.run_deadline_s, settings.finalize_reserve_s)
    metrics = ExecutionMetrics(started_at=datetime.now(UTC))
    policy = RetryPolicy(max_attempts=settings.retry_max_attempts)
    search, extract = apply_faults(providers.search, providers.extract, case.fault)
    routes = providers.routes or ModelRoutes.single(providers.model, providers.mode.value)
    if case.fault is not None and case.fault.model != "none":
        fault_mode = case.fault.model
        routes = routes.wrap(lambda client: FaultyModel(client, fault_mode))
    tools = ToolRunner(
        search=search,
        extract=extract,
        budget=budget,
        deadline=deadline,
        metrics=metrics,
        policy=policy,
        search_timeout_s=settings.search_timeout_s,
        extract_timeout_s=settings.extract_timeout_s,
        concurrency=settings.max_concurrency,
    )
    caller = ModelCaller(
        routes, budget=budget, deadline=deadline, metrics=metrics, policy=policy, timeout_s=settings.model_timeout_s
    )

    result = SystemResult(system="baseline", status="completed")
    started = time.perf_counter()
    try:
        found = await tools.search_web(SearchArgs(query=case.question[:240], max_results=min(10, settings.max_pages_per_run)))
        if not found.ok:
            raise ProviderError("search", found.error_kind or "unknown", found.error or "search failed")  # type: ignore[arg-type]
        urls = [h.url for h in found.hits if is_safe_public_url(h.url)][: settings.max_pages_per_run]
        pages = (await tools.read_sources(urls, query=case.question)).pages if urls else []
        if not pages:
            result.status = "insufficient_evidence"
            result.abstained = True
        else:
            input_text, payload = baseline_input(case.question, pages)
            data = await caller.call(baseline_spec(settings), input_text, payload, finalizing=True)
            result.claims, result.invalid_citations = score_baseline_claims(data, payload["pages"])
            result.abstained = data.get("answerable") is False or not result.claims
            if result.abstained:
                result.status = "insufficient_evidence"
    except (ProviderError, BudgetExhausted, DeadlineReached) as exc:
        result.status = "failed"
        result.error = str(exc) or type(exc).__name__
        result.abstained = True

    result.latency_s = round(time.perf_counter() - started, 2)
    result.cost_usd = round(budget.spent_usd, 5)
    result.cost_uncertain = budget.cost_uncertain
    result.model_calls = metrics.model_calls
    result.model_fallbacks = metrics.model_fallbacks
    result.models_used = dict(metrics.models_used)
    result.input_tokens = budget.input_tokens
    result.output_tokens = budget.output_tokens
    result.search_calls = metrics.search_calls
    result.pages_read = metrics.pages_read
    measurable = {
        "answers": result.status == "completed" and bool(result.claims),
        "citations_resolve": result.invalid_citations == 0,
        "abstains": result.abstained,
        "fails_closed": result.status == "failed" and not result.claims,
    }
    # The baseline returns prose and claims only, so table, entity, ambiguity, and conflict checks do not apply.
    result.checks = {name: measurable.get(name) for name in case.checks}
    return result


# ---------------------------------------------------------------------------
# Suite


def _fixture_providers(scenario: Scenario, *, baseline: bool) -> Providers:
    model: ModelClient = FixtureOnePass(scenario) if baseline else FixtureModel(scenario)
    return Providers(FixtureSearch(scenario), FixtureExtract(scenario), model, Mode.fixture)


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def summarize(results: list[SystemResult]) -> dict[str, Any]:
    claims = sum(len(r.claims) for r in results)
    supported = sum(r.count(SupportVerdict.supported) for r in results)
    checks = [v for r in results for v in r.checks.values() if v is not None]
    covered = [r for r in results if r.criteria_total]
    latencies = [r.latency_s for r in results]
    return {
        "runs": len(results),
        "checks_passed": sum(checks),
        "checks_total": len(checks),
        "claims": claims,
        "supported": supported,
        "partially_supported": sum(r.count(SupportVerdict.partially_supported) for r in results),
        "not_supported": sum(r.count(SupportVerdict.not_supported) for r in results),
        "supported_rate": round(supported / claims, 3) if claims else None,
        "invalid_citations": sum(r.invalid_citations for r in results),
        "criteria_covered": sum(r.criteria_covered or 0 for r in covered),
        "criteria_total": sum(r.criteria_total or 0 for r in covered),
        "reported_criteria_supported": sum(r.reported_criteria_supported or 0 for r in covered)
        if any(r.reported_criteria_supported is not None for r in results)
        else None,
        "latency_s_median": round(statistics.median(latencies), 2) if latencies else None,
        "latency_s_total": round(sum(latencies), 2),
        "cost_usd_total": round(sum(r.cost_usd for r in results), 4),
        "cost_uncertain": any(r.cost_uncertain for r in results),
    }


def _routing(settings: Settings) -> dict[str, Any] | None:
    """The Groq models and tasks used besides the primary model, with their prices; None without a Groq key."""
    if settings.groq_api_key is None:
        return None
    models = {settings.groq_model: [settings.groq_input_usd_per_mtok, settings.groq_output_usd_per_mtok]}
    if settings.groq_fallback_model:
        models[settings.groq_fallback_model] = [
            settings.groq_fallback_input_usd_per_mtok,
            settings.groq_fallback_output_usd_per_mtok,
        ]
    return {
        "groq_models_usd_per_mtok_in_out": models,
        "groq_tasks": settings.groq_task_list,
        "groq_max_request_tokens": settings.groq_max_request_tokens,
        "fallback": settings.model_fallback,
    }


def _save_report(directory: Path, case_id: str, report: ResearchReport) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{case_id}.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")


async def run_suite(
    cases: list[EvalCase],
    settings: Settings,
    mode: Mode,
    *,
    baseline: bool = True,
    max_spend: float = 3.0,
    reports_dir: Path | None = None,
    log=lambda message: None,
) -> dict[str, Any]:
    live_providers: Providers | None = None
    closers: list[Any] = []
    if mode == Mode.live:
        from .llm import live_routes
        from .tools import TavilyClient

        assert settings.tavily_api_key is not None and settings.openai_api_key is not None
        tavily = TavilyClient(settings.tavily_api_key.get_secret_value())
        routes, models = live_routes(settings)
        live_providers = Providers(tavily, tavily, routes.primary, Mode.live, routes=routes)
        closers = [tavily, *models]

    spent, stopped_early = 0.0, False
    out_cases: list[dict[str, Any]] = []
    agent_results: list[SystemResult] = []
    baseline_results: list[SystemResult] = []
    try:
        for n, case in enumerate(cases, 1):
            scenario = load_scenarios()[case.scenario]
            row: dict[str, Any] = {
                "id": case.id,
                "category": case.category,
                "question": case.question,
                "expected": case.expected,
                "fault": case.fault.model_dump() if case.fault else None,
            }
            systems = ["agent", "baseline"] if baseline else ["agent"]
            for system in systems:
                cap = min(settings.max_cost_usd_per_run, max_spend - spent)
                if mode == Mode.live and cap < MIN_RUN_CAP_USD:
                    stopped_early = True
                    break
                # Each run's budget reserves worst-case cost before every call, so the suite cannot pass max_spend.
                run_settings = settings.model_copy(update={"max_cost_usd_per_run": cap, "enable_fault_injection": True})
                providers = live_providers or _fixture_providers(scenario, baseline=system == "baseline")
                if system == "agent":
                    result, report = await run_agent(case, run_settings, providers)
                    criteria = report.plan.criteria if report.plan else []
                    row["agent_plan_criteria"] = [c.description for c in criteria]
                    if reports_dir is not None:
                        _save_report(reports_dir, case.id, report)
                else:
                    result = await run_baseline(case, run_settings, providers)
                cov = criteria_coverage(result.claims, criteria)
                if cov is not None:
                    result.criteria_covered, result.criteria_total = cov
                spent += result.cost_usd
                row[system] = asdict(result)
                (agent_results if system == "agent" else baseline_results).append(result)
                log(
                    f"[{n}/{len(cases)}] {case.id} {system}: {result.status}"
                    f" ({result.latency_s:.1f}s, ${result.cost_usd:.4f}; suite ${spent:.4f})"
                )
            out_cases.append(row)
            if stopped_early:
                log(f"Stopping: the remaining budget (${max_spend - spent:.4f}) is below ${MIN_RUN_CAP_USD} per run.")
                break
    finally:
        for closer in closers:
            await closer.aclose()

    return {
        "suite": "predixion-eval",
        "mode": mode.value,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": settings.research_model if mode == Mode.live else FIXTURE_MODEL,
        "reasoning_effort": settings.reasoning_effort if mode == Mode.live else None,
        "sdk_version": live_providers.model.sdk_version if live_providers else None,
        "prompt_version": PROMPT_VERSION,
        "git_commit": _git_commit(),
        "prices": {
            "model_input_usd_per_mtok": settings.model_input_usd_per_mtok,
            "model_output_usd_per_mtok": settings.model_output_usd_per_mtok,
            "tavily_usd_per_credit": settings.tavily_usd_per_credit,
        }
        if mode == Mode.live
        else None,
        "routing": _routing(settings) if mode == Mode.live else None,
        "limits": {
            "max_rounds": settings.max_rounds,
            "max_pages_per_run": settings.max_pages_per_run,
            "max_cost_usd_per_run": settings.max_cost_usd_per_run,
            "max_model_attempts": settings.max_model_attempts,
            "run_deadline_s": settings.run_deadline_s,
        },
        "baseline": "one search, up to max_pages_per_run pages, one model call with quoted citations; same model",
        "scoring": "lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge",
        "max_spend_usd": max_spend,
        "spent_usd": round(spent, 4),
        "stopped_early": stopped_early,
        "cases": out_cases,
        "summary": {"agent": summarize(agent_results), "baseline": summarize(baseline_results) if baseline else None},
    }


# ---------------------------------------------------------------------------
# Output


def _ratio(a: int | None, b: int | None) -> str:
    return f"{a}/{b}" if b else "-"


def _checks_text(checks: dict[str, bool | None]) -> str:
    return ", ".join(f"{k} {'pass' if v else 'FAIL' if v is False else 'n/a'}" for k, v in checks.items())


def _routing_lines(routing: dict[str, Any] | None) -> list[str]:
    if not routing:
        return []
    models = ", ".join(routing["groq_models_usd_per_mtok_in_out"])
    tasks = ", ".join(routing["groq_tasks"]) or "none"
    fallback = "on" if routing["fallback"] else "off"
    return [f"- Groq models: {models}; Groq-first tasks: {tasks}; fallback between providers: {fallback}"]


def render_results(results: dict[str, Any]) -> str:
    lines = [
        f"# Evaluation results: {results['mode']} mode",
        "",
        f"- Run at: {results['run_at']} (UTC)",
        f"- Model: {results['model']}"
        + (f", reasoning effort {results['reasoning_effort']}" if results["reasoning_effort"] else "")
        + (f", openai SDK {results['sdk_version']}" if results["sdk_version"] else ""),
        f"- Prompt version: {results['prompt_version']}; git commit: {results['git_commit'] or 'uncommitted'}",
        *_routing_lines(results.get("routing")),
        f"- Baseline: {results['baseline']}",
        f"- Scoring: {results['scoring']}",
        f"- Spend: ${results['spent_usd']:.4f} of ${results['max_spend_usd']:.2f} limit"
        + (" (stopped early)" if results["stopped_early"] else ""),
    ]
    if results["mode"] == "fixture":
        lines.append("- Fixture mode: synthetic pages and scripted models. These numbers check the pipeline, not model quality.")
    lines += [
        "",
        "## Per case",
        "",
        "| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims"
        " | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in results["cases"]:
        a, b = c.get("agent"), c.get("baseline")

        def sup(r: dict[str, Any] | None) -> str:
            if r is None:
                return "-"
            return f"{sum(1 for x in r['claims'] if x['verdict'] == 'supported')}/{len(r['claims'])}"

        def cov(r: dict[str, Any] | None) -> str:
            return _ratio(r["criteria_covered"], r["criteria_total"]) if r else "-"

        lat = " / ".join(f"{r['latency_s']:.1f}" if r else "-" for r in (a, b))
        cost = " / ".join(f"{r['cost_usd']:.4f}" if r else "-" for r in (a, b))
        status = f"{a['status']} ({a['stop_reason']})" if a else "not run"
        lines.append(f"| {c['id']} | {c['category']} | {status} | {sup(a)} | {sup(b)} | {cov(a)} / {cov(b)} | {lat} | {cost} |")

    lines += ["", "## Summary", "", "| Metric | Agent | Baseline |", "|---|---|---|"]
    sa, sb = results["summary"]["agent"], results["summary"]["baseline"] or {}
    for key in (
        "runs",
        "checks_passed",
        "checks_total",
        "claims",
        "supported",
        "partially_supported",
        "not_supported",
        "supported_rate",
        "invalid_citations",
        "criteria_covered",
        "criteria_total",
        "reported_criteria_supported",
        "latency_s_median",
        "latency_s_total",
        "cost_usd_total",
    ):
        lines.append(f"| {key} | {sa.get(key, '-')} | {sb.get(key, '-')} |")

    lines += ["", "## Expected vs actual", ""]
    for c in results["cases"]:
        a, b = c.get("agent"), c.get("baseline")
        lines += [f"### {c['id']}", "", f"Question: {c['question']}", "", f"Expected: {c['expected']}", ""]
        if a:
            lines.append(
                f"- Agent: {a['status']}, stop reason {a['stop_reason']}, confidence {a['confidence']}. "
                f"Checks: {_checks_text(a['checks'])}."
            )
        if b:
            detail = f" Error: {b['error']}." if b["error"] else ""
            lines.append(f"- Baseline: {b['status']}.{detail} Checks: {_checks_text(b['checks'])}.")
        for r in (a, b):
            weak = [x for x in (r or {}).get("claims", []) if x["verdict"] != "supported"][:2]
            for x in weak:
                lines.append(f'  - {r["system"]} claim scored {x["verdict"]}: "{_clip(x["text"])}" ({x["issue"]})')  # type: ignore[index]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def select_cases(ids: list[str] | None) -> list[EvalCase]:
    if not ids:
        return list(CASES)
    known = {c.id: c for c in CASES}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(f"unknown case id(s): {', '.join(unknown)}; choose from {', '.join(known)}")
    return [known[i] for i in ids]


def main(args: argparse.Namespace, settings: Settings) -> int:
    mode = Mode(args.mode)
    try:
        cases = select_cases(args.scenario)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    update: dict[str, Any] = {}
    if args.model:
        update["research_model"] = args.model
    if args.input_usd_per_mtok is not None:
        update["model_input_usd_per_mtok"] = args.input_usd_per_mtok
    if args.output_usd_per_mtok is not None:
        update["model_output_usd_per_mtok"] = args.output_usd_per_mtok
    if mode == Mode.live:
        if not settings.live_available:
            print(f"Live evaluation needs {', '.join(settings.missing_live_credentials())}.", file=sys.stderr)
            return 2
        if args.model and args.model != settings.research_model and len(update) < 3:
            print("--model needs --input-usd-per-mtok and --output-usd-per-mtok so spend limits use its prices.", file=sys.stderr)
            return 2
    settings = settings.model_copy(update=update)

    results = asyncio.run(
        run_suite(
            cases,
            settings,
            mode,
            baseline=not args.no_baseline,
            max_spend=args.max_spend,
            reports_dir=Path(args.save_reports) if args.save_reports else None,
            log=lambda message: print(message, file=sys.stderr),
        )
    )
    name = f"{mode.value}-{settings.research_model}" if mode == Mode.live else "fixture"
    out = Path(args.out or f"evals/results/{name}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(render_results(results), encoding="utf-8")
    print(f"Wrote {out} and {out.with_suffix('.md')}", file=sys.stderr)

    sa, sb = results["summary"]["agent"], results["summary"]["baseline"]
    print(
        f"Agent: checks {sa['checks_passed']}/{sa['checks_total']}, supported {sa['supported']}/{sa['claims']}, "
        f"criteria {sa['criteria_covered']}/{sa['criteria_total']}, ${sa['cost_usd_total']:.4f}"
    )
    if sb:
        print(
            f"Baseline: checks {sb['checks_passed']}/{sb['checks_total']}, supported {sb['supported']}/{sb['claims']}, "
            f"criteria {sb['criteria_covered']}/{sb['criteria_total']}, ${sb['cost_usd_total']:.4f}"
        )
    return 0 if sa["checks_passed"] == sa["checks_total"] and not results["stopped_early"] else 1
