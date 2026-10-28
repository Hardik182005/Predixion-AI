from __future__ import annotations

from predixion.contracts import (
    CheckedText,
    ClaimDisposition,
    ComparisonCell,
    ComparisonRow,
    ComparisonTable,
    CoverageStatus,
    Criterion,
    CriterionCoverage,
    CriterionKind,
    EligibilityCheck,
    EligibilityStatus,
    EntityResult,
    Evidence,
    Finding,
    Passage,
    PlannedQuery,
    ResearchPlan,
    RunStatus,
    Source,
    SupportVerdict,
    TaskType,
)
from predixion.fixtures import judge_support
from predixion.grounding import (
    Draft,
    apply_verdict,
    check_references,
    decide_status,
    enumerate_claims,
    finalize_draft,
    parse_draft,
    polarity_conflicts,
    validate_evidence,
)

PASSAGE = (
    "Milvus supports billion-scale vector search with GPU indexes. Its “IVF_PQ” index reduces memory at the cost of some recall."
)


def _validate(items: list[dict], existing: list[Evidence] | None = None):
    source = Source(
        id="S1", url="https://milvus.io/docs", canonical_url="https://milvus.io/docs", domain="milvus.io", title="Docs"
    )
    return validate_evidence(
        items,
        passages={"S1.P1": Passage(id="S1.P1", text=PASSAGE, start=0)},
        sources={"S1": source},
        criteria={"K1": Criterion(id="K1", description="Scale", kind=CriterionKind.general)},
        existing=existing or [],
        known_entities=["Milvus"],
        round_no=1,
    )


def _item(**overrides) -> dict:
    item = {
        "passage_id": "S1.P1",
        "quote": "Milvus supports billion-scale vector search",
        "claim": "Milvus supports billion-scale vector search.",
        "criterion_ids": ["K1"],
        "entity": "milvus",
    }
    item.update(overrides)
    return item


def test_evidence_with_exact_quote_is_accepted() -> None:
    batch = _validate([_item(), _item(quote='Its "IVF_PQ" index reduces memory', claim="IVF_PQ saves memory.")])
    assert [e.id for e in batch.accepted] == ["E1", "E2"]
    assert batch.accepted[0].entity == "Milvus"
    assert batch.accepted[0].first_party
    assert batch.rejected == []


def test_evidence_rejections() -> None:
    batch = _validate(
        [
            _item(passage_id="S7.P1"),
            _item(quote="Milvus is the fastest vector database on the market"),
            _item(quote="Milvus supports ... GPU indexes"),
            _item(criterion_ids=["K99"]),
            _item(quote="", claim="anything"),
            _item(),
            _item(),
        ]
    )
    assert [r.reason for r in batch.rejected] == [
        "unknown_passage",
        "quote_not_found",
        "quote_not_found",
        "unknown_criterion",
        "empty",
        "duplicate",
    ]
    assert len(batch.accepted) == 1


def test_evidence_ids_continue_after_existing() -> None:
    first = _validate([_item()]).accepted
    second = _validate([_item(quote="index reduces memory at the cost of some recall")], existing=first)
    assert [e.id for e in second.accepted] == ["E2"]


# ---------------------------------------------------------------------------
# Claim checking


def _draft() -> Draft:
    return Draft(
        short_answer=CheckedText(text="Milvus scales to billions of vectors.", evidence_ids=["E1"]),
        findings=[
            Finding(text="Milvus supports GPU indexes.", evidence_ids=["E1", "E99", "../E1"]),
            Finding(text="Milvus is used by every Fortune 500 company.", evidence_ids=["E42"]),
        ],
        comparison=ComparisonTable(
            criteria=["K1"],
            rows=[
                ComparisonRow(entity="Milvus", cells=[ComparisonCell(criterion_id="K1", text="Billions", evidence_ids=["E1"])])
            ],
        ),
        entities=[
            EntityResult(
                name="Milvus",
                included=True,
                summary=CheckedText(text="Open-source vector database.", evidence_ids=["E1"]),
                eligibility=[
                    EligibilityCheck(criterion_id="K1", status=EligibilityStatus.met, text="Open source", evidence_ids=["E1"])
                ],
            )
        ],
    )


def test_reference_check_removes_fake_evidence_ids() -> None:
    draft = _draft()
    refs = enumerate_claims(draft)
    assert [r.claim.id for r in refs] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    removed = check_references(refs, {"E1"})
    assert removed == 3
    assert draft.findings[0].evidence_ids == ["E1"]
    assert draft.findings[1].evidence_ids == []
    assert refs[2].claim.verdict == SupportVerdict.not_supported


def test_judge_rejects_real_quote_that_does_not_support_the_claim() -> None:
    evidence = ["Milvus supports billion-scale vector search with GPU indexes."]
    assert judge_support("Milvus is the fastest vector database.", evidence)[0] == "not_supported"
    assert judge_support("Milvus guarantees zero downtime upgrades.", evidence)[0] == "not_supported"
    assert judge_support("Milvus supports billion-scale vector search.", evidence) == ("supported", None)
    assert judge_support("Anything at all.", [])[0] == "not_supported"


def test_finalize_removes_unsupported_claims_everywhere() -> None:
    draft = _draft()
    refs = enumerate_claims(draft)
    check_references(refs, {"E1"})
    verdicts = {
        "C1": SupportVerdict.not_supported,
        "C2": SupportVerdict.supported,
        "C3": SupportVerdict.not_supported,
        "C4": SupportVerdict.not_supported,
        "C5": SupportVerdict.partially_supported,
        "C6": SupportVerdict.not_supported,
    }
    for ref in refs:
        apply_verdict(ref, verdicts[ref.claim.id], "test")
    row = draft.comparison.rows[0]  # type: ignore[union-attr]
    removed = finalize_draft(draft)

    assert "Milvus scales to billions of vectors." in removed
    assert draft.short_answer.text.startswith("No short answer could be verified")
    assert draft.short_answer.evidence_ids == []
    assert [f.text for f in draft.findings] == ["Milvus supports GPU indexes."]
    cell = row.cells[0]
    assert cell.unknown and cell.disposition == ClaimDisposition.removed
    entity = draft.entities[0]
    assert entity.summary is not None and entity.summary.disposition == ClaimDisposition.qualified
    assert entity.eligibility[0].status == EligibilityStatus.unknown
    assert not entity.included
    assert entity.exclusion_reason == "Eligibility not confirmed by verified evidence."
    assert draft.comparison is None  # its only row was an entity that dropped off the list


def _plan(task_type: TaskType) -> ResearchPlan:
    return ResearchPlan(
        objective="o",
        task_type=task_type,
        interpretation="i",
        criteria=[
            Criterion(id="K1", description="Open source", kind=CriterionKind.eligibility),
            Criterion(id="K2", description="Filtering", kind=CriterionKind.dimension),
        ],
        queries=[PlannedQuery(id="Q1", text="q", purpose="p")],
    )


def test_parse_draft_moves_inline_citations_into_evidence_ids() -> None:
    draft = parse_draft(
        {
            "short_answer": {"text": "Qdrant filters well [E2; E3].", "evidence_ids": ["E1"]},
            "key_findings": [{"text": "Weaviate has hybrid search (E4, E5). It is open source (E6).", "evidence_ids": []}],
        },
        _plan(TaskType.explainer),
    )
    assert draft.short_answer.text == "Qdrant filters well."
    assert draft.short_answer.evidence_ids == ["E1", "E2", "E3"]
    assert draft.findings[0].text == "Weaviate has hybrid search. It is open source."
    assert draft.findings[0].evidence_ids == ["E4", "E5", "E6"]


def test_discovery_comparison_keeps_only_listed_entities() -> None:
    def entity(name: str, included: bool) -> dict:
        status = "met" if included else "unknown"
        return {
            "name": name,
            "included": included,
            "eligibility": [{"criterion_id": "K1", "status": status, "text": "t", "evidence_ids": ["E1"]}],
        }

    cells = [{"criterion_id": "K2", "text": "Payload filters", "evidence_ids": ["E1"], "unknown": False}]
    data = {
        "short_answer": {"text": "Three candidates.", "evidence_ids": ["E1"]},
        "comparison": {"criteria": ["K2"], "rows": [{"entity": n, "cells": cells} for n in ("Qdrant", "Weaviate", "Chroma")]},
        "entities": [entity("Qdrant", True), entity("Weaviate", True), entity("Chroma", False)],
    }
    draft = parse_draft(data, _plan(TaskType.entity_discovery))
    for ref in enumerate_claims(draft):
        apply_verdict(ref, SupportVerdict.supported, None)
    finalize_draft(draft)
    assert draft.comparison is not None
    assert [r.entity for r in draft.comparison.rows] == ["Qdrant", "Weaviate"]
    assert parse_draft(data, _plan(TaskType.explainer)).comparison is None


# ---------------------------------------------------------------------------
# Status and conflicts


def _coverage(status: CoverageStatus, required: bool = True) -> CriterionCoverage:
    return CriterionCoverage(criterion_id="K1", description="d", kind=CriterionKind.general, required=required, status=status)


def _refs(verdict: SupportVerdict):
    draft = Draft(short_answer=CheckedText(text="Claim.", evidence_ids=["E1"]))
    refs = enumerate_claims(draft)
    refs[0].claim.verdict = verdict
    return refs


def test_decide_status() -> None:
    supported = _refs(SupportVerdict.supported)
    rejected = _refs(SupportVerdict.not_supported)
    ok = [_coverage(CoverageStatus.supported), _coverage(CoverageStatus.missing, required=False)]
    gap = [_coverage(CoverageStatus.weak)]

    def status(coverage, refs, *, ran=True, n=3, limit=False) -> RunStatus:
        return decide_status(coverage=coverage, refs=refs, verification_ran=ran, evidence_count=n, hit_limit=limit)

    assert status(ok, supported) == RunStatus.completed
    assert status(ok, supported, n=0) == RunStatus.insufficient_evidence
    assert status(ok, rejected) == RunStatus.insufficient_evidence
    assert status(gap, supported) == RunStatus.partial
    assert status(ok, supported, limit=True) == RunStatus.partial
    assert status(ok, supported, ran=False) == RunStatus.partial


def test_unanswered_report_with_only_a_caveat_finding_is_insufficient_evidence() -> None:
    """A removed short answer plus no supported required criterion is not a partial answer.

    Seen live on a nonexistent product: the only surviving finding said the sources describe a different
    project, every required criterion was missing or stale, and the run was labelled partial.
    """
    draft = Draft(
        short_answer=CheckedText(text="It costs $99.", evidence_ids=["E1"]),
        findings=[Finding(text="The sources describe a different project.", evidence_ids=["E1"])],
    )
    refs = enumerate_claims(draft)
    apply_verdict(refs[0], SupportVerdict.not_supported, "not in evidence")
    apply_verdict(refs[1], SupportVerdict.supported, None)
    nothing = [_coverage(CoverageStatus.missing), _coverage(CoverageStatus.stale)]
    assert decide_status(coverage=nothing, refs=refs, verification_ran=True, evidence_count=1, hit_limit=False) == (
        RunStatus.insufficient_evidence
    )
    # One supported required criterion, or a surviving short answer, keeps it a partial answer.
    some = [_coverage(CoverageStatus.supported), _coverage(CoverageStatus.missing)]
    assert decide_status(coverage=some, refs=refs, verification_ran=True, evidence_count=1, hit_limit=False) == RunStatus.partial
    apply_verdict(refs[0], SupportVerdict.partially_supported, "hedged")
    assert (
        decide_status(coverage=nothing, refs=refs, verification_ran=True, evidence_count=1, hit_limit=False) == RunStatus.partial
    )


def _ev(eid: str, polarity: str, entity: str | None = "SQLite") -> Evidence:
    return Evidence(
        id=eid,
        source_id="S1",
        passage_id="S1.P1",
        quote="q" * 20,
        claim="c",
        criterion_ids=["K1"],
        entity=entity,
        polarity=polarity,  # type: ignore[arg-type]
    )


def test_polarity_conflicts_are_detected_per_entity() -> None:
    conflicts = polarity_conflicts([_ev("E1", "supports"), _ev("E2", "contradicts"), _ev("E3", "supports", entity="Postgres")])
    assert len(conflicts) == 1
    assert conflicts[0].evidence_ids == ["E1", "E2"]
    assert conflicts[0].entity == "SQLite"
    assert polarity_conflicts([_ev("E1", "supports"), _ev("E2", "supports")]) == []
