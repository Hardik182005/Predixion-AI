"""Typed contracts shared by the workflow, API, CLI, evaluation, and frontend.

Identifiers for sources (S#), passages (S#.P#), evidence (E#), criteria (K#),
claims (C#), and queries (Q#) are assigned by application code. The model may
only *select* identifiers that already exist in the current run.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

QUESTION_MIN_CHARS = 8
QUESTION_MAX_CHARS = 1_000
MAX_SEED_URLS = 3
RUN_ID_PATTERN = r"^run_[0-9a-f]{24}$"
RUN_ID_RE = re.compile(RUN_ID_PATTERN)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=400)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Enums


class Mode(StrEnum):
    live = "live"
    fixture = "fixture"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    # Terminal outcomes:
    completed = "completed"  # required criteria addressed and verified
    partial = "partial"  # useful verified findings, but criteria missing or limits hit
    insufficient_evidence = "insufficient_evidence"  # providers worked; evidence did not support an answer
    failed = "failed"  # could not research (provider outage, credentials, internal error)
    cancelled = "cancelled"  # stopped by the user
    interrupted = "interrupted"  # process stopped while the run was active


TERMINAL_STATUSES = frozenset(
    {
        RunStatus.completed,
        RunStatus.partial,
        RunStatus.insufficient_evidence,
        RunStatus.failed,
        RunStatus.cancelled,
        RunStatus.interrupted,
    }
)


class StopReason(StrEnum):
    criteria_satisfied = "criteria_satisfied"
    rounds_exhausted = "rounds_exhausted"
    diminishing_returns = "diminishing_returns"
    no_actionable_gaps = "no_actionable_gaps"
    deadline_reached = "deadline_reached"
    budget_exhausted = "budget_exhausted"
    page_budget_exhausted = "page_budget_exhausted"
    no_relevant_sources = "no_relevant_sources"
    provider_unavailable = "provider_unavailable"
    provider_auth_error = "provider_auth_error"
    model_output_invalid = "model_output_invalid"
    cancelled_by_user = "cancelled_by_user"
    process_interrupted = "process_interrupted"
    internal_error = "internal_error"


class TaskType(StrEnum):
    comparison = "comparison"
    entity_discovery = "entity_discovery"
    pros_cons = "pros_cons"
    explainer = "explainer"


class CriterionKind(StrEnum):
    dimension = "dimension"  # an attribute to research for each option/entity
    eligibility = "eligibility"  # a condition an entity must satisfy to be included
    general = "general"  # a question-level fact or consideration


class CoverageStatus(StrEnum):
    supported = "supported"
    weak = "weak"  # only low-suitability evidence (e.g. first-party marketing for a comparative claim)
    conflicting = "conflicting"
    stale = "stale"  # evidence exists but is older than the freshness window or undated
    missing = "missing"


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class SourceTier(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class SourceKind(StrEnum):
    official_docs = "official_docs"
    code_repository = "code_repository"
    academic = "academic"
    news = "news"
    company_site = "company_site"
    blog = "blog"
    community = "community"
    aggregator = "aggregator"
    unknown = "unknown"


class SourceState(StrEnum):
    candidate = "candidate"  # discovered by search, not read
    read = "read"  # content extracted and usable
    failed = "failed"  # extraction failed or produced unusable content
    filtered = "filtered"  # rejected by filtering rules
    duplicate = "duplicate"  # duplicate URL or substantially duplicate content


class ClaimLocation(StrEnum):
    short_answer = "short_answer"
    finding = "finding"
    comparison_cell = "comparison_cell"
    entity = "entity"
    eligibility = "eligibility"


class ClaimKind(StrEnum):
    fact = "fact"
    interpretation = "interpretation"
    recommendation = "recommendation"


class SupportVerdict(StrEnum):
    supported = "supported"
    partially_supported = "partially_supported"
    not_supported = "not_supported"
    unchecked = "unchecked"  # verification could not run (budget/provider); never shown as verified


class ClaimDisposition(StrEnum):
    kept = "kept"
    qualified = "qualified"  # kept with an explicit qualification
    removed = "removed"


class EligibilityStatus(StrEnum):
    met = "met"
    not_met = "not_met"
    unknown = "unknown"


class ToolName(StrEnum):
    search_web = "search_web"
    read_sources = "read_sources"


class EventType(StrEnum):
    status = "status"
    stage = "stage"
    plan = "plan"
    tool = "tool"
    coverage = "coverage"
    warning = "warning"
    report = "report"
    error = "error"


class Stage(StrEnum):
    validate = "validate"
    plan = "plan"
    search = "search"
    filter = "filter"
    read = "read"
    extract = "extract"
    assess = "assess"
    follow_up = "follow_up"
    synthesize = "synthesize"
    verify = "verify"
    repair = "repair"
    finalize = "finalize"


# ---------------------------------------------------------------------------
# Request


class FaultInjection(Model):
    """Deterministic failure injection for demos/tests. Disabled unless explicitly enabled."""

    search: Literal["none", "unavailable", "rate_limited", "auth", "empty"] = "none"
    extract: Literal["none", "unavailable", "partial", "all_failed"] = "none"
    model: Literal["none", "unavailable", "malformed", "refusal"] = "none"


class ResearchRequest(Model):
    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=QUESTION_MIN_CHARS, max_length=QUESTION_MAX_CHARS),
    ]
    mode: Mode | None = None
    seed_urls: list[Annotated[str, StringConstraints(max_length=2_048)]] = Field(default_factory=list, max_length=MAX_SEED_URLS)
    max_rounds: int | None = Field(default=None, ge=1, le=4)
    fault: FaultInjection | None = None

    @field_validator("question")
    @classmethod
    def _no_control_chars(cls, value: str) -> str:
        if any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
            raise ValueError("question contains control characters")
        return value


# ---------------------------------------------------------------------------
# Plan


class Criterion(Model):
    id: str
    description: str
    kind: CriterionKind
    required: bool = True
    needs_freshness: bool = False
    comparative: bool = False  # comparative/performance claims need independent evidence
    key_terms: list[str] = Field(default_factory=list, max_length=8)


class PlannedQuery(Model):
    id: str
    text: str
    purpose: str
    criterion_ids: list[str] = Field(default_factory=list)
    round: int = 1
    topic: Literal["general", "news"] = "general"


class ResearchPlan(Model):
    objective: str
    task_type: TaskType
    interpretation: str
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=8)
    ambiguity_note: str | None = None
    freshness_days: int | None = None
    target_entity_count: int | None = None
    candidate_entities: list[str] = Field(default_factory=list, max_length=10)
    criteria: list[Criterion] = Field(min_length=1, max_length=8)
    queries: list[PlannedQuery] = Field(min_length=1)
    steps: list[str] = Field(default_factory=list, max_length=10)


# ---------------------------------------------------------------------------
# Tools


class SearchArgs(Model):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=240)]
    max_results: int = Field(6, ge=1, le=10)
    topic: Literal["general", "news"] = "general"
    time_range: Literal["year", "month", "week"] | None = None


class ReadArgs(Model):
    source_ids: list[str] = Field(min_length=1, max_length=8)


class ResearchAction(Model):
    tool: ToolName
    search: SearchArgs | None = None
    read: ReadArgs | None = None
    reason: str = ""
    criterion_ids: list[str] = Field(default_factory=list)


class SearchHit(Model):
    url: str
    title: str = ""
    snippet: str = ""
    score: float | None = None
    published_date: str | None = None


class ExtractedPage(Model):
    url: str
    content: str


class ItemFailure(Model):
    item: str
    error: str
    retryable: bool = False


class ToolResult(Model):
    """Outcome of one tool invocation, preserving per-item success and failure."""

    tool: ToolName
    ok: bool
    items_requested: int
    items_succeeded: int
    hits: list[SearchHit] = Field(default_factory=list)
    pages: list[ExtractedPage] = Field(default_factory=list)
    failures: list[ItemFailure] = Field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None
    attempts: int = 1
    cached: bool = False
    credits: float | None = None
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Sources and evidence


class Passage(Model):
    id: str  # S#.P#
    text: str
    start: int  # offset in normalized source content


class Source(Model):
    id: str
    url: str
    canonical_url: str
    domain: str
    title: str
    snippet: str = ""
    kind: SourceKind = SourceKind.unknown
    tier: SourceTier = SourceTier.medium
    state: SourceState = SourceState.candidate
    state_reason: str | None = None
    query_ids: list[str] = Field(default_factory=list)
    provider_score: float | None = None
    rank_score: float = 0.0
    retrieved_at: datetime | None = None
    published_at: str | None = None
    published_at_origin: Literal["provider_estimate", "page_text", "unknown"] = "unknown"
    content_hash: str | None = None
    content_chars: int = 0
    duplicate_of: str | None = None
    injection_suspected: bool = False
    fixture: bool = False
    round: int = 1


class Evidence(Model):
    id: str  # E#
    source_id: str
    passage_id: str
    quote: str
    claim: str
    criterion_ids: list[str]
    entity: str | None = None
    polarity: Literal["supports", "contradicts"] = "supports"
    first_party: bool = False
    round: int = 1


class EvidenceRejection(Model):
    passage_id: str | None
    reason: Literal["unknown_passage", "quote_not_found", "unknown_criterion", "empty", "duplicate", "limit"]


class Conflict(Model):
    description: str
    criterion_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    entity: str | None = None
    resolution: str | None = None


class CriterionCoverage(Model):
    criterion_id: str
    description: str
    kind: CriterionKind
    required: bool
    status: CoverageStatus
    evidence_ids: list[str] = Field(default_factory=list)
    independent_sources: int = 0
    note: str | None = None


# ---------------------------------------------------------------------------
# Report


class CheckedText(Model):
    claim_id: str | None = None
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    verdict: SupportVerdict = SupportVerdict.unchecked
    disposition: ClaimDisposition = ClaimDisposition.kept
    note: str | None = None


class Finding(CheckedText):
    kind: ClaimKind = ClaimKind.fact
    criterion_ids: list[str] = Field(default_factory=list)


class ComparisonCell(CheckedText):
    criterion_id: str
    unknown: bool = False


class ComparisonRow(Model):
    entity: str
    cells: list[ComparisonCell]


class ComparisonTable(Model):
    criteria: list[str]  # criterion ids in column order
    rows: list[ComparisonRow]


class EligibilityCheck(CheckedText):
    criterion_id: str
    status: EligibilityStatus


class EntityResult(Model):
    name: str
    included: bool
    summary: CheckedText | None = None
    eligibility: list[EligibilityCheck] = Field(default_factory=list)
    exclusion_reason: str | None = None


class Claim(Model):
    id: str
    location: ClaimLocation
    kind: ClaimKind
    text: str
    evidence_ids: list[str]
    verdict: SupportVerdict = SupportVerdict.unchecked
    issue: str | None = None
    repaired: bool = False


class VerificationSummary(Model):
    claims_checked: int = 0
    supported: int = 0
    partially_supported: int = 0
    not_supported: int = 0
    unchecked: int = 0
    invalid_references_removed: int = 0
    repair_attempted: bool = False
    removed_claims: list[str] = Field(default_factory=list)
    note: str | None = None


class ConfidenceAssessment(Model):
    level: Confidence
    explanation: str
    factors: dict[str, str | float | int]


class StageTiming(Model):
    stage: Stage
    ms: float


class ExecutionMetrics(Model):
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float | None = None
    first_event_ms: float | None = None
    stage_timings: list[StageTiming] = Field(default_factory=list)
    rounds: int = 0
    search_calls: int = 0
    extract_calls: int = 0
    pages_requested: int = 0
    pages_read: int = 0
    model_calls: int = 0
    model_attempts: int = 0
    retries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cost_uncertain: bool = False
    tavily_credits: float = 0.0
    sources_discovered: int = 0
    sources_filtered: int = 0
    evidence_accepted: int = 0
    evidence_rejected: int = 0


class ExecutionInfo(Model):
    mode: Mode
    model: str
    sdk_version: str | None = None
    prompt_version: str
    reasoning_effort: str | None = None
    limits: dict[str, float | int]
    metrics: ExecutionMetrics


class ResearchReport(Model):
    run_id: str
    question: str
    status: RunStatus
    stop_reason: StopReason | None = None
    stop_detail: str | None = None
    mode: Mode
    short_answer: CheckedText
    key_findings: list[Finding]
    comparison: ComparisonTable | None = None
    entities: list[EntityResult] = Field(default_factory=list)
    sources: list[Source]
    evidence: list[Evidence]
    coverage: list[CriterionCoverage]
    unresolved_criteria: list[str]
    conflicts: list[Conflict] = Field(default_factory=list)
    confidence: ConfidenceAssessment
    limitations: list[str]
    assumptions: list[str]
    next_steps: list[str]
    plan: ResearchPlan | None = None
    claims: list[Claim] = Field(default_factory=list)
    verification: VerificationSummary
    execution: ExecutionInfo
    created_at: datetime


# ---------------------------------------------------------------------------
# Runs and events


class RunEvent(Model):
    seq: int
    ts: datetime
    type: EventType
    stage: Stage | None = None
    message: str
    data: dict | None = None


class RunSummary(Model):
    run_id: str
    status: RunStatus
    question: str
    mode: Mode
    created_at: datetime
    updated_at: datetime
    stop_reason: StopReason | None = None


class RunView(RunSummary):
    report: ResearchReport | None = None
    plan: ResearchPlan | None = None
    last_event_seq: int = 0
    error: str | None = None


class StartRunResponse(Model):
    run_id: str
    status: RunStatus
    reused: bool = False
    events_url: str
    run_url: str
