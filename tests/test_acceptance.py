"""Frozen acceptance set for the evidence-quality pass.

Each case states an independently authored expectation (not derived from the code under test):
compound criteria, per-entity coverage and freshness, conjunctive eligibility, empty required sets,
conservative aliases, explained conflicts, confidence invariants, and finalization under storage
failures. The cases were written and run against the baseline before the behavior changed; the
baseline outcomes are recorded in docs/improvements.md.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import pydantic
import pytest

from predixion.contracts import (
    CheckedText,
    ClaimDisposition,
    Conflict,
    CoverageStatus,
    Criterion,
    CriterionCoverage,
    CriterionKind,
    EventType,
    Evidence,
    Finding,
    Mode,
    PlannedQuery,
    ResearchPlan,
    ResearchRequest,
    RunStatus,
    Source,
    SourceState,
    SourceTier,
    StopReason,
    SupportVerdict,
    TaskType,
)
from predixion.fixtures import FixtureExtract, FixtureModel
from predixion.grounding import (
    Draft,
    apply_verdict,
    assess_confidence,
    canonical_entity,
    compute_coverage,
    enumerate_claims,
    finalize_draft,
    parse_draft,
    polarity_conflicts,
    required_satisfied,
)
from predixion.logs import error_location
from predixion.orchestrator import Providers, ResearchRun, normalize_plan
from predixion.runs import RunManager, wait_for
from predixion.store import Store

from .conftest import RUN_ID, TODAY, EventLog, SlowSearch, fixture_providers, make_settings, scenario

OWNER = "local"


def _crit(i: int, desc: str, kind: CriterionKind = CriterionKind.general, **kw) -> Criterion:
    return Criterion(id=f"K{i}", description=desc, kind=kind, **kw)


def _plan(criteria: list[Criterion], task_type: TaskType = TaskType.explainer, **kw) -> ResearchPlan:
    return ResearchPlan(
        objective="o",
        task_type=task_type,
        interpretation="i",
        criteria=criteria,
        queries=[PlannedQuery(id="Q1", text="q", purpose="p")],
        **kw,
    )


def _src(
    i: int, url: str, published: str | None = None, tier: SourceTier = SourceTier.medium, content_hash: str | None = None
) -> Source:
    return Source(
        id=f"S{i}",
        url=url,
        canonical_url=url,
        domain=url.split("/")[2],
        title="t",
        published_at=published,
        tier=tier,
        state=SourceState.read,
        content_hash=content_hash,
    )


def _ev(
    i: int, sid: str, crit: str, entity: str | None = None, *, fp: bool = False, pol: str = "supports", claim: str = "c"
) -> Evidence:
    return Evidence(
        id=f"E{i}",
        source_id=sid,
        passage_id=f"{sid}.P1",
        quote="q" * 20,
        claim=claim,
        criterion_ids=[crit],
        entity=entity,
        first_party=fp,
        polarity=pol,  # type: ignore[arg-type]
    )


def _raw_criterion(cid: str, desc: str, kind: str = "general", **kw) -> dict:
    return {
        "id": cid,
        "description": desc,
        "kind": kind,
        "required": True,
        "needs_freshness": False,
        "comparative": False,
        "key_terms": [],
        "parts": [],
        **kw,
    }


# ---------------------------------------------------------------------------
# Atomic criteria and truthful coverage


def test_compound_criterion_is_split_and_blocks_completion_until_every_part_has_evidence() -> None:
    raw = {
        "task_type": "comparison",
        "candidate_entities": ["Milvus"],
        "criteria": [
            _raw_criterion(
                "K1",
                "Verify an open-source core and identify its license",
                "dimension",
                parts=["open-source core", "license identified"],
            )
        ],
        "queries": [{"text": "milvus license", "purpose": "p", "criterion_ids": ["K1"], "topic": "general"}],
    }
    plan = normalize_plan(raw, question="q", max_queries=3)
    assert [c.id for c in plan.criteria] == ["K1", "K2"]
    assert all(c.group == "Verify an open-source core and identify its license" for c in plan.criteria)
    assert plan.criteria[1].description.endswith("license identified")
    assert plan.queries[0].criterion_ids == ["K1", "K2"]  # a query aimed at the parent targets every part

    coverage = compute_coverage(plan, [_ev(1, "S1", "K1", "Milvus")], {"S1": _src(1, "https://milvus.io/docs")}, today=TODAY)
    assert [(c.criterion_id, c.status) for c in coverage] == [("K1", CoverageStatus.supported), ("K2", CoverageStatus.missing)]
    assert not required_satisfied(coverage)


def test_parts_stay_within_the_plan_bound_and_a_single_part_is_not_split() -> None:
    raw = {
        "task_type": "explainer",
        "criteria": [_raw_criterion(f"K{i}", f"criterion {i}", parts=["a", "b", "c", "d"]) for i in range(1, 7)],
        "queries": [],
    }
    plan = normalize_plan(raw, question="q", max_queries=3)
    assert len(plan.criteria) == 8
    single = normalize_plan(
        {"criteria": [_raw_criterion("K1", "one thing", parts=["only part"])], "queries": []}, question="q", max_queries=3
    )
    assert len(single.criteria) == 1 and single.criteria[0].group is None


def test_freshness_is_judged_per_entity_in_a_comparison() -> None:
    plan = _plan(
        [_crit(1, "pricing", CriterionKind.dimension, needs_freshness=True)],
        TaskType.comparison,
        candidate_entities=["A", "B", "C"],
        freshness_days=365,
    )
    sources = {
        "S1": _src(1, "https://a.org/p", "2026-09-01"),
        "S2": _src(2, "https://b.org/p", "2021-01-01"),
        "S3": _src(3, "https://c.org/p", None),
    }
    coverage = compute_coverage(
        plan, [_ev(1, "S1", "K1", "A"), _ev(2, "S2", "K1", "B"), _ev(3, "S3", "K1", "C")], sources, today=TODAY
    )
    assert coverage[0].status == CoverageStatus.stale
    assert coverage[0].stale_entities == ["B", "C"]
    assert "B, C" in (coverage[0].note or "")
    # All three fresh: supported.
    fresh = {k: _src(int(k[1]), v.url, "2026-09-01") for k, v in sources.items()}
    assert (
        compute_coverage(plan, [_ev(1, "S1", "K1", "A"), _ev(2, "S2", "K1", "B"), _ev(3, "S3", "K1", "C")], fresh, today=TODAY)[
            0
        ].status
        == CoverageStatus.supported
    )


def test_one_entity_cannot_satisfy_another_entitys_dimension() -> None:
    plan = _plan([_crit(1, "license", CriterionKind.dimension)], TaskType.comparison, candidate_entities=["A", "B", "C"])
    coverage = compute_coverage(plan, [_ev(1, "S1", "K1", "A")], {"S1": _src(1, "https://a.org/p")}, today=TODAY)
    assert coverage[0].status == CoverageStatus.weak
    assert coverage[0].missing_entities == ["B", "C"]


def test_discovery_eligibility_names_the_unverified_entities() -> None:
    plan = _plan(
        [_crit(1, "Headquartered in India", CriterionKind.eligibility), _crit(2, "B2B SaaS", CriterionKind.eligibility)],
        TaskType.entity_discovery,
        target_entity_count=5,
    )
    evidence = [_ev(1, "S1", "K1", "X"), _ev(2, "S1", "K2", "X"), _ev(3, "S2", "K2", "Y")]
    coverage = compute_coverage(
        plan, evidence, {"S1": _src(1, "https://x.com/about"), "S2": _src(2, "https://y.com/about")}, today=TODAY
    )
    k1 = coverage[0]
    assert k1.status == CoverageStatus.weak
    assert k1.missing_entities == ["Y"]
    assert "Not established for: Y" in (k1.note or "")


def test_entity_with_an_omitted_eligibility_check_is_not_included() -> None:
    plan = _plan(
        [_crit(1, "Headquartered in India", CriterionKind.eligibility), _crit(2, "B2B SaaS", CriterionKind.eligibility)],
        TaskType.entity_discovery,
    )
    data = {
        "short_answer": {"text": "X qualifies.", "evidence_ids": ["E1"]},
        "entities": [
            {
                "name": "X",
                "included": True,
                "summary": None,
                "exclusion_reason": None,
                "eligibility": [{"criterion_id": "K1", "status": "met", "text": "X is in Bengaluru", "evidence_ids": ["E1"]}],
            }
        ],
    }
    draft = parse_draft(data, plan)
    for ref in enumerate_claims(draft):
        apply_verdict(ref, SupportVerdict.supported, None)
    finalize_draft(draft, ["K1", "K2"])
    assert not draft.entities[0].included
    assert draft.entities[0].exclusion_reason == "Eligibility not established for: K2."


def test_a_plan_with_no_required_criterion_cannot_be_satisfied_by_nothing() -> None:
    assert not required_satisfied([])
    optional_only = [
        CriterionCoverage(
            criterion_id="K1", description="d", kind=CriterionKind.general, required=False, status=CoverageStatus.missing
        )
    ]
    assert not required_satisfied(optional_only)
    raw = {"task_type": "explainer", "criteria": [_raw_criterion("K1", "x", required=False)], "queries": []}
    assert all(c.required for c in normalize_plan(raw, question="what is x", max_queries=3).criteria)


def test_entity_aliases_match_conservatively() -> None:
    assert canonical_entity("milvus", ["Milvus"]) == "Milvus"
    assert canonical_entity("Keka Technologies Pvt. Ltd.", ["Keka Technologies"]) == "Keka Technologies"
    assert canonical_entity("Darwinbox, Inc", ["Darwinbox"]) == "Darwinbox"
    assert canonical_entity("Kekatech", ["Keka"]) == "Kekatech"
    assert canonical_entity("Milvus Lite", ["Milvus"]) == "Milvus Lite"
    assert canonical_entity("Zoho People", ["Zoho"]) == "Zoho People"  # a product line is not conflated with its parent
    assert canonical_entity("AI Labs", ["AI"]) == "AI Labs"


# ---------------------------------------------------------------------------
# Conflicts


def test_code_detected_conflicts_quote_both_sides_and_ask_for_review() -> None:
    sources = {"S1": _src(1, "https://a.org/x", "2026-01-05"), "S2": _src(2, "https://b.org/y", None)}
    criteria = {"K1": _crit(1, "Write concurrency")}
    evidence = [
        _ev(1, "S1", "K1", "SQLite", claim="SQLite handles multiple writers through one app server"),
        _ev(2, "S2", "K1", "SQLite", pol="contradicts", claim="Any app with more than one writer needs PostgreSQL"),
    ]
    conflicts = polarity_conflicts(evidence, sources, criteria)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.review_needed
    assert "Write concurrency" in c.description and "SQLite" in c.description
    assert "handles multiple writers" in c.description and "needs PostgreSQL" in c.description
    assert "E1, a.org, dated 2026-01-05" in c.description and "E2, b.org, undated" in c.description
    assert c.evidence_ids == ["E1", "E2"]


def test_facts_that_differ_without_opposite_polarity_are_not_a_conflict() -> None:
    evidence = [
        _ev(1, "S1", "K1", "Qdrant", claim="v1.8 lacks the feature"),
        _ev(2, "S2", "K1", "Qdrant", claim="v1.9 adds the feature"),
    ]
    assert polarity_conflicts(evidence) == []
    # Opposite polarity about different entities is not a conflict either.
    assert polarity_conflicts([_ev(1, "S1", "K1", "A"), _ev(2, "S2", "K1", "B", pol="contradicts")]) == []


# ---------------------------------------------------------------------------
# Confidence from the final claims


def _ok_coverage(*ids: str) -> list[CriterionCoverage]:
    return [
        CriterionCoverage(
            criterion_id=i, description="d", kind=CriterionKind.general, required=True, status=CoverageStatus.supported
        )
        for i in ids
    ]


def _refs(findings_ids: list[list[str]], answer_ids: list[str] | None = None, verdicts: dict[str, SupportVerdict] | None = None):
    draft = Draft(
        short_answer=CheckedText(text="Answer.", evidence_ids=answer_ids if answer_ids is not None else ["E1"]),
        findings=[Finding(text=f"F{i}", evidence_ids=ids) for i, ids in enumerate(findings_ids, 1)],
    )
    refs = enumerate_claims(draft)
    for ref in refs:
        apply_verdict(ref, (verdicts or {}).get(ref.claim.id, SupportVerdict.supported), None)
    return refs


def _confidence(evidence, sources, refs, coverage, conflicts=(), criteria=None, status=RunStatus.completed):
    return assess_confidence(
        status=status,
        coverage=coverage,
        refs=refs,
        evidence=evidence,
        sources=sources,
        conflicts=list(conflicts),
        verification_ran=True,
        criteria=criteria,
    )


TWO_SITES = {"S1": _src(1, "https://a.org/x"), "S2": _src(2, "https://b.org/x")}


def test_uncited_sources_cannot_raise_confidence() -> None:
    refs = _refs([["E1", "E2"]])
    base = _confidence([_ev(1, "S1", "K1"), _ev(2, "S2", "K1")], TWO_SITES, refs, _ok_coverage("K1"))
    more_ev = [_ev(1, "S1", "K1"), _ev(2, "S2", "K1"), _ev(3, "S3", "K1"), _ev(4, "S4", "K1"), _ev(5, "S5", "K1")]
    more_src = {
        **TWO_SITES,
        "S3": _src(3, "https://c.org/x"),
        "S4": _src(4, "https://d.org/x"),
        "S5": _src(5, "https://e.org/x", tier=SourceTier.high),
    }
    bigger = _confidence(more_ev, more_src, refs, _ok_coverage("K1"))
    assert bigger.level == base.level
    assert bigger.factors["independent_domains"] == base.factors["independent_domains"] == 2
    assert bigger.factors["cited_evidence"] == 2


def test_a_copy_of_a_cited_source_is_not_corroboration() -> None:
    refs = _refs([["E1", "E2"]])
    copy = {"S1": _src(1, "https://a.org/x", content_hash="h1"), "S2": _src(2, "https://mirror.net/x", content_hash="h1")}
    c = _confidence([_ev(1, "S1", "K1"), _ev(2, "S2", "K1")], copy, refs, _ok_coverage("K1"))
    assert c.factors["independent_domains"] == 1
    assert c.level != "high"


def test_removing_the_only_support_for_a_required_claim_cannot_improve_the_outcome() -> None:
    refs = _refs([["E1"], ["E2"]])
    before = _confidence([_ev(1, "S1", "K1"), _ev(2, "S2", "K1")], TWO_SITES, refs, _ok_coverage("K1"))
    weaker = _refs([["E1"], ["E2"]], verdicts={"C2": SupportVerdict.not_supported})
    coverage = [
        CriterionCoverage(
            criterion_id="K1", description="d", kind=CriterionKind.general, required=True, status=CoverageStatus.weak
        )
    ]
    after = _confidence([_ev(1, "S1", "K1"), _ev(2, "S2", "K1")], TWO_SITES, weaker, coverage)
    order = {"low": 0, "medium": 1, "high": 2}
    assert order[after.level.value] < order[before.level.value]


def test_an_unresolved_conflict_prevents_high() -> None:
    refs = _refs([["E1", "E2"]])
    ev = [_ev(1, "S1", "K1"), _ev(2, "S2", "K1")]
    assert _confidence(ev, TWO_SITES, refs, _ok_coverage("K1")).level.value == "high"
    conflict = Conflict(description="x", criterion_ids=["K1"], evidence_ids=["E1", "E2"])
    assert _confidence(ev, TWO_SITES, refs, _ok_coverage("K1"), conflicts=[conflict]).level.value != "high"
    resolved = conflict.model_copy(update={"resolution": "the newer source supersedes the older one"})
    assert _confidence(ev, TWO_SITES, refs, _ok_coverage("K1"), conflicts=[resolved]).level.value == "high"


def test_one_authoritative_source_can_establish_a_narrow_documented_fact() -> None:
    refs = _refs([["E1"]])
    docs = {"S1": _src(1, "https://docs.example.org/x", tier=SourceTier.high)}
    criteria = [_crit(1, "Feature X is available")]
    assert _confidence([_ev(1, "S1", "K1")], docs, refs, _ok_coverage("K1"), criteria=criteria).level.value == "high"
    # The same single site cannot carry a comparison, or a non-authoritative page.
    comparative = [_crit(1, "fastest option", comparative=True)]
    assert _confidence([_ev(1, "S1", "K1")], docs, refs, _ok_coverage("K1"), criteria=comparative).level.value != "high"
    blog = {"S1": _src(1, "https://blog.example.org/x")}
    assert _confidence([_ev(1, "S1", "K1")], blog, refs, _ok_coverage("K1"), criteria=criteria).level.value != "high"


def test_vendor_only_comparative_evidence_prevents_high_even_with_several_sites() -> None:
    refs = _refs([["E1", "E2"]])
    ev = [_ev(1, "S1", "K1", "Acme", fp=True), _ev(2, "S2", "K1", "Acme", fp=True)]
    sources = {"S1": _src(1, "https://acme.com/blog"), "S2": _src(2, "https://acme.io/docs")}
    criteria = [_crit(1, "fastest", comparative=True)]
    c = _confidence(ev, sources, refs, _ok_coverage("K1"), criteria=criteria)
    assert c.level.value != "high"
    assert c.factors["comparative_criteria_without_independent_evidence"] == 1
    # First-party evidence for a non-comparative fact about the vendor's own product is fine.
    own = [_crit(1, "supports hybrid search")]
    assert _confidence(ev, sources, refs, _ok_coverage("K1"), criteria=own).level.value == "high"


def test_a_removed_short_answer_caps_confidence() -> None:
    refs = _refs([["E1"], ["E2"]], verdicts={"C1": SupportVerdict.not_supported})
    draft_refs = refs
    assert draft_refs[0].target.disposition == ClaimDisposition.removed
    c = _confidence([_ev(1, "S1", "K1"), _ev(2, "S2", "K1")], TWO_SITES, draft_refs, _ok_coverage("K1"))
    assert c.level.value != "high"
    assert c.factors["short_answer_supported"] == "no"
    assert "short answer was not supported" in c.explanation


# ---------------------------------------------------------------------------
# Follow-up targets the gaps that matter


def _run_with_plan() -> ResearchRun:
    sc = scenario("agent_memory")
    run = ResearchRun(
        RUN_ID, ResearchRequest(question=sc.question), make_settings(), fixture_providers(sc), EventLog(), today=TODAY
    )
    run.plan = _plan(
        [
            _crit(1, "benchmarks", CriterionKind.dimension, key_terms=["latency", "benchmark"]),
            _crit(2, "license terms", CriterionKind.dimension, key_terms=["license", "commercial use"]),
        ],
        TaskType.comparison,
        candidate_entities=["Milvus", "Weaviate"],
    )
    run.queries = [PlannedQuery(id="Q1", text="vector database benchmarks", purpose="p", criterion_ids=["K1"])]
    return run


def test_a_required_missing_gap_gets_a_search_when_the_model_only_reads_other_candidates() -> None:
    run = _run_with_plan()
    gaps = [
        CriterionCoverage(
            criterion_id="K1", description="benchmarks", kind=CriterionKind.dimension, required=True, status=CoverageStatus.weak
        ),
        CriterionCoverage(
            criterion_id="K2",
            description="license terms",
            kind=CriterionKind.dimension,
            required=True,
            status=CoverageStatus.missing,
            missing_entities=["Milvus", "Weaviate"],
        ),
    ]
    queries = run._cover_untargeted_gaps(gaps, [], ["S1"] if False else [], next_round=2)
    assert len(queries) == 1
    assert queries[0].criterion_ids == ["K2"]
    assert queries[0].text == "Milvus license commercial use"
    # A gap already targeted by a query gets nothing extra, and the query cap is respected.
    again = run._cover_untargeted_gaps(gaps, list(queries), [], next_round=2)
    assert len(again) == 1


def test_follow_up_page_slots_are_spread_across_gap_queries() -> None:
    run = _run_with_plan()
    q_bench = PlannedQuery(id="Q2", text="milvus benchmark latency", purpose="p", criterion_ids=["K1"], round=2)
    q_lic = PlannedQuery(id="Q3", text="weaviate license commercial use", purpose="p", criterion_ids=["K2"], round=2)
    for i, (qid, url, score) in enumerate(
        [
            ("Q2", "https://bench1.org/a", 0.9),
            ("Q2", "https://bench2.org/b", 0.8),
            ("Q3", "https://weaviate.io/license", 0.3),
            ("Q3", "https://osi.org/license", 0.2),
        ],
        1,
    ):
        sid = f"S{i}"
        run.sources[sid] = Source(
            id=sid, url=url, canonical_url=url, domain=url.split("/")[2], title="t", query_ids=[qid], rank_score=score
        )
    chosen = run._best_per_query([q_bench, q_lic], 2, exclude=set())
    assert chosen == ["S1", "S3"]  # one slot per gap query, not the two best-ranked benchmark pages
    assert run._best_per_query([q_bench, q_lic], 1, exclude=set()) == ["S1"]


# ---------------------------------------------------------------------------
# Finalization under storage failure


class FlakyStore(Store):
    """In-memory store whose write methods fail on demand."""

    def __init__(self, path: str = ":memory:") -> None:
        super().__init__(path)
        self.fail: set[str] = set()
        self.calls: dict[str, int] = {}

    def _maybe_fail(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1
        if name in self.fail:
            raise RuntimeError(f"injected: {name} failed (disk full) with secret payload QUESTION-TEXT-7")

    def save_report(self, run_id, report):
        self._maybe_fail("save_report")
        super().save_report(run_id, report)

    def set_status(self, run_id, status, *, stop_reason=None, error=None):
        self._maybe_fail("set_status")
        super().set_status(run_id, status, stop_reason=stop_reason, error=error)

    def append_event(self, run_id, event):
        self._maybe_fail("append_event")
        super().append_event(run_id, event)


QUESTION = scenario("agent_memory").question


def _log_dump(caplog: pytest.LogCaptureFixture) -> str:
    """Everything a log handler could see: messages plus structured fields."""
    return caplog.text + " ".join(str(getattr(r, "fields", "")) for r in caplog.records)


async def _finished(manager: RunManager, fail: set[str]) -> tuple[str, list]:
    store: FlakyStore = manager.store  # type: ignore[assignment]
    started = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)
    store.fail = fail
    queue: asyncio.Queue = asyncio.Queue()
    manager._active[started.run_id].subscribers.add(queue)
    await wait_for(manager, started.run_id)
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return started.run_id, items


async def test_report_save_failure_releases_the_run_and_reports_it_honestly(caplog: pytest.LogCaptureFixture) -> None:
    manager = RunManager(make_settings(MAX_CONCURRENT_RUNS=1, MAX_QUEUED_RUNS=0), FlakyStore())
    with caplog.at_level(logging.ERROR, logger="predixion.runs"):
        run_id, items = await _finished(manager, {"save_report"})
    assert run_id not in manager._active
    assert manager._active == {}
    assert items[-1] is None  # subscribers were told the run is over
    terminal = [e for e in items if e is not None][-1]
    assert terminal.type == EventType.status and terminal.data["terminal"] and terminal.data["persisted"] is False
    assert terminal.data["status"] == "failed"
    assert "could not be saved" in terminal.message
    view = manager.store.get_run(run_id, OWNER)
    assert view is not None and view.report is None
    assert (view.status, view.stop_reason) == (RunStatus.failed, StopReason.internal_error)
    assert view.error and "could not be saved" in view.error
    assert not any(e.type == EventType.report for e in manager.store.events_after(run_id, 0))
    # The error was logged by category and location, never with the exception text.
    record = next(r for r in caplog.records if r.getMessage() == "report persist failed")
    assert record.fields["error"] == "RuntimeError" and record.fields["where"].startswith("runs.py:")
    assert "QUESTION-TEXT-7" not in _log_dump(caplog) and "disk full" not in _log_dump(caplog)
    # Capacity was released: the next run is admitted and completes normally.
    manager.store.fail = set()
    second = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)
    await wait_for(manager, second.run_id)
    assert manager.store.get_status(second.run_id, OWNER) == RunStatus.completed
    await manager.shutdown()


async def test_persistent_storage_failure_is_recovered_as_interrupted_on_restart(tmp_path) -> None:
    path = str(tmp_path / "runs.db")
    manager = RunManager(make_settings(PREDIXION_DB_PATH=path), FlakyStore(path))
    run_id, items = await _finished(manager, {"save_report", "set_status", "append_event"})
    assert run_id not in manager._active
    assert items[-1] is None
    terminal = [e for e in items if e is not None][-1]
    assert terminal.data["terminal"] and terminal.data["persisted"] is False
    assert manager.store.get_status(run_id, OWNER) in (RunStatus.queued, RunStatus.running)  # nothing durable could be written
    await manager.shutdown()
    # The next process marks it interrupted and gives reconnecting clients a terminal event.
    restarted = RunManager(make_settings(PREDIXION_DB_PATH=path), Store(path))
    await restarted.start()
    try:
        view = restarted.store.get_run(run_id, OWNER)
        assert view is not None and (view.status, view.stop_reason) == (RunStatus.interrupted, StopReason.process_interrupted)
        assert restarted.store.events_after(run_id, 0)[-1].data["terminal"]
        assert restarted._active == {}  # recovery never restarts the research
    finally:
        await restarted.shutdown()


async def test_event_persistence_failure_during_finalization_does_not_lose_the_report() -> None:
    manager = RunManager(make_settings(), FlakyStore())
    run_id, items = await _finished(manager, {"append_event"})
    assert items[-1] is None
    view = manager.store.get_run(run_id, OWNER)
    assert view is not None and view.report is not None and view.status == RunStatus.completed
    assert run_id not in manager._active
    await manager.shutdown()


async def test_finalization_is_idempotent_and_cancel_after_the_end_is_harmless() -> None:
    manager = RunManager(make_settings(), FlakyStore())
    store: FlakyStore = manager.store  # type: ignore[assignment]
    started = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)
    await wait_for(manager, started.run_id)
    events_before = len(store.events_after(started.run_id, 0))
    saves_before = store.calls.get("save_report", 0)
    view = store.get_run(started.run_id, OWNER)
    assert view is not None and view.report is not None
    active = type("Done", (), {"done": True})()
    manager._finish(active, view.report, None)  # type: ignore[arg-type]
    assert len(store.events_after(started.run_id, 0)) == events_before
    assert store.calls.get("save_report", 0) == saves_before
    assert manager.cancel(started.run_id, OWNER) == RunStatus.completed
    assert len(store.events_after(started.run_id, 0)) == events_before
    await manager.shutdown()


async def test_a_broken_subscriber_does_not_block_the_others() -> None:
    manager = RunManager(make_settings(), FlakyStore())
    started = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)

    class Broken:
        def put_nowait(self, item):
            raise RuntimeError("closed")

    good: asyncio.Queue = asyncio.Queue()
    manager._active[started.run_id].subscribers.update({Broken(), good})  # type: ignore[arg-type]
    await wait_for(manager, started.run_id)
    assert started.run_id not in manager._active
    items = []
    while not good.empty():
        items.append(good.get_nowait())
    assert items[-1] is None
    await manager.shutdown()


async def test_stream_slot_is_released_exactly_once() -> None:
    manager = RunManager(make_settings(MAX_SSE_PER_RUN=1), Store(":memory:"))
    slot = manager.acquire_stream("run_x")
    assert manager._sse_total == 1 and manager._sse_per_run == {"run_x": 1}
    slot.release()
    slot.release()  # the body's finally and the response background task may both call it
    assert manager._sse_total == 0 and manager._sse_per_run == {}
    second = manager.acquire_stream("run_x")
    assert manager._sse_total == 1
    second.release()
    await manager.shutdown()


async def test_stream_slot_is_released_when_the_client_disconnects_mid_stream() -> None:
    import httpx

    from predixion.api import create_app

    sc = scenario("agent_memory")
    app = create_app(make_settings())
    providers = Providers(SlowSearch(sc, delay_s=5.0), FixtureExtract(sc), FixtureModel(sc), Mode.fixture)
    async with app.router.lifespan_context(app):
        manager = app.state.manager
        manager._providers = lambda mode, question: providers
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            run_id = (await client.post("/api/runs", json={"question": sc.question})).json()["run_id"]
            async with client.stream("GET", f"/api/runs/{run_id}/events") as response:
                async for _ in response.aiter_bytes():
                    break
            await asyncio.sleep(0.05)
            assert manager._sse_total == 0 and manager._sse_per_run == {}
            manager.cancel(run_id, OWNER)
            await wait_for(manager, run_id)


# ---------------------------------------------------------------------------
# Logs never carry request or page text unless LOG_CONTENT is on


def test_error_location_names_the_application_frame() -> None:
    try:
        pydantic.TypeAdapter(int).validate_python("not-an-int")
    except pydantic.ValidationError as exc:
        where = error_location(exc)
    assert where.endswith(".py:" + where.rsplit(":", 1)[1]) and where != "unknown"


@pytest.mark.parametrize("log_content", [False, True])
async def test_unexpected_exception_text_is_logged_only_with_log_content(
    caplog: pytest.LogCaptureFixture, log_content: bool
) -> None:
    manager = RunManager(make_settings(LOG_CONTENT=log_content), Store(":memory:"))
    started = manager.start_run(ResearchRequest(question=QUESTION), owner=OWNER)

    async def boom():
        pydantic.TypeAdapter(int).validate_python("SENSITIVE-PAYLOAD-XYZ")

    manager._active[started.run_id].research.execute = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR, logger="predixion.runs"):
        await wait_for(manager, started.run_id)
    assert manager.store.get_status(started.run_id, OWNER) == RunStatus.failed
    record = next(r for r in caplog.records if r.getMessage() == "run failed unexpectedly")
    assert record.fields["error"] == "ValidationError" and record.fields["where"] != "unknown"
    assert ("SENSITIVE-PAYLOAD-XYZ" in _log_dump(caplog)) is log_content
    await manager.shutdown()


def test_compute_coverage_marks_missing_discovery_entities_from_the_plan() -> None:
    # Candidates named by the planner count as entities to establish even before any evidence names them.
    plan = _plan(
        [_crit(1, "open source", CriterionKind.eligibility)],
        TaskType.entity_discovery,
        candidate_entities=["A", "B"],
        target_entity_count=2,
    )
    coverage = compute_coverage(plan, [], {}, today=date(2026, 10, 28))
    assert coverage[0].status == CoverageStatus.missing and coverage[0].missing_entities == ["A", "B"]
