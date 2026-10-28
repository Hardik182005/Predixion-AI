"""Source-dependency analysis: what in a finished report depends on one source?

Works on a copy of a completed report using only its claim -> evidence -> source links. It makes no
model, search, or extraction calls and never changes the original report. The result says which
claims would lose every citation without the source and which would keep some; it does not say
whether the surviving citations still support a claim, and it does not re-verify anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import ClaimLocation, ResearchReport, SupportVerdict

NOTE = "Source-dependency analysis, not a new fact check: a surviving citation may support only part of a claim."


@dataclass
class ClaimDependency:
    claim_id: str
    location: ClaimLocation
    text: str
    verdict: SupportVerdict
    removed_evidence_ids: list[str]
    remaining_evidence_ids: list[str]


@dataclass
class DependencyAnalysis:
    source_ids: list[str]  # the removed source family
    family_reason: str
    evidence_removed: list[str]
    claims_lost: list[ClaimDependency] = field(default_factory=list)  # every cited passage came from the family
    claims_weakened: list[ClaimDependency] = field(default_factory=list)  # some cited passages remain
    criteria_to_reassess: list[str] = field(default_factory=list)
    note: str = NOTE


def _order(sid: str) -> int:
    return int(sid[1:]) if sid[1:].isdigit() else 0


def duplicate_family(report: ResearchReport, source_id: str) -> tuple[list[str], str]:
    """The source plus sources conservatively identified as copies of it: same content hash, or a recorded duplicate link."""
    sources = {s.id: s for s in report.sources}
    if source_id not in sources:
        raise KeyError(source_id)
    root = sources[source_id]
    family = {source_id}
    for s in report.sources:
        same_hash = root.content_hash is not None and s.content_hash == root.content_hash
        linked = s.duplicate_of == source_id or root.duplicate_of == s.id
        if same_hash or linked:
            family.add(s.id)
    ordered = sorted(family, key=_order)
    reason = (
        "the source alone" if len(ordered) == 1 else "the source and its recorded copies (same content hash or duplicate link)"
    )
    return ordered, reason


def source_dependencies(report: ResearchReport, source_id: str, *, include_duplicates: bool = True) -> DependencyAnalysis:
    """Analyze a copy of `report` with `source_id` (and its copies) removed from the evidence graph."""
    copy = report.model_copy(deep=True)
    if source_id not in {s.id for s in copy.sources}:
        raise KeyError(source_id)
    family, reason = duplicate_family(copy, source_id) if include_duplicates else ([source_id], "the source alone")
    removed_evidence = [e.id for e in copy.evidence if e.source_id in family]
    removed = set(removed_evidence)
    valid = {e.id for e in copy.evidence}
    analysis = DependencyAnalysis(source_ids=family, family_reason=reason, evidence_removed=removed_evidence)
    criteria: set[str] = set()
    for claim in copy.claims:
        cited = [eid for eid in claim.evidence_ids if eid in valid]
        gone = [eid for eid in cited if eid in removed]
        if not gone:
            continue
        left = [eid for eid in cited if eid not in removed]
        dep = ClaimDependency(claim.id, claim.location, claim.text, claim.verdict, gone, left)
        (analysis.claims_weakened if left else analysis.claims_lost).append(dep)
        for e in copy.evidence:
            if e.id in gone:
                criteria.update(e.criterion_ids)
    analysis.criteria_to_reassess = sorted(criteria, key=_order)
    return analysis


def render_dependencies(analysis: DependencyAnalysis) -> str:
    lines = [
        f"Removed: {', '.join(analysis.source_ids)} ({analysis.family_reason}); {len(analysis.evidence_removed)} evidence item(s).",
        f"Claims that lose every citation: {len(analysis.claims_lost)}",
    ]
    lines += [f"  - {d.claim_id} [{d.location.value}] {d.text[:140]}" for d in analysis.claims_lost]
    lines.append(f"Claims that keep some citations: {len(analysis.claims_weakened)}")
    lines += [
        f"  - {d.claim_id} [{d.location.value}] keeps {', '.join(d.remaining_evidence_ids)}; loses {', '.join(d.removed_evidence_ids)}"
        for d in analysis.claims_weakened
    ]
    lines.append("Criteria to reassess: " + (", ".join(analysis.criteria_to_reassess) or "none"))
    lines.append(analysis.note)
    return "\n".join(lines)
