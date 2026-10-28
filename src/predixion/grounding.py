"""Evidence validation, criteria coverage, claim checking, and confidence.

All of this is deterministic application logic. The model proposes evidence
and claims; this module decides what is accepted and how it is labeled.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .contracts import (
    CheckedText,
    Claim,
    ClaimDisposition,
    ClaimKind,
    ClaimLocation,
    ComparisonCell,
    ComparisonRow,
    ComparisonTable,
    Confidence,
    ConfidenceAssessment,
    Conflict,
    CoverageStatus,
    Criterion,
    CriterionCoverage,
    CriterionKind,
    EligibilityCheck,
    EligibilityStatus,
    EntityResult,
    Evidence,
    EvidenceRejection,
    Finding,
    Passage,
    ResearchPlan,
    RunStatus,
    Source,
    SourceState,
    SourceTier,
    SupportVerdict,
    TaskType,
)
from .sources import entity_token, is_first_party, normalize_for_match, parse_date
from .urls import registrable_domain

MAX_EVIDENCE_PER_RUN = 80
MAX_EVIDENCE_PER_SOURCE = 8
MIN_QUOTE_CHARS = 12
MAX_QUOTE_CHARS = 500
MAX_TEXT_CHARS = 1_200
EVIDENCE_ID_RE = re.compile(r"^E\d{1,4}$")

# ---------------------------------------------------------------------------
# Evidence


def canonical_entity(name: str | None, known: list[str]) -> str | None:
    if not name or not name.strip():
        return None
    name = " ".join(name.split())[:80]
    token = entity_token(name)
    for k in known:
        kt = entity_token(k)
        if kt and (kt == token or (len(kt) >= 4 and (kt in token or token in kt))):
            return k
    return name


def quote_in_passage(quote: str, passage: str) -> bool:
    q = normalize_for_match(quote).strip(" .\"'")
    if len(q) < MIN_QUOTE_CHARS or "..." in q:
        return False
    return q in normalize_for_match(passage)


@dataclass
class EvidenceBatch:
    accepted: list[Evidence]
    rejected: list[EvidenceRejection]


def validate_evidence(
    raw_items: list[dict[str, Any]],
    *,
    passages: dict[str, Passage],
    sources: dict[str, Source],
    criteria: dict[str, Criterion],
    existing: list[Evidence],
    known_entities: list[str],
    round_no: int,
) -> EvidenceBatch:
    """Accept only evidence whose quote appears in an offered passage and whose criteria exist."""
    accepted: list[Evidence] = []
    rejected: list[EvidenceRejection] = []
    seen = {(e.passage_id, normalize_for_match(e.quote)) for e in existing}
    per_source: dict[str, int] = defaultdict(int)
    for e in existing:
        per_source[e.source_id] += 1
    next_n = len(existing) + 1
    for item in raw_items:
        pid = str(item.get("passage_id") or "")
        quote = " ".join(str(item.get("quote") or "").split())
        claim = " ".join(str(item.get("claim") or "").split())[:MAX_TEXT_CHARS]
        if pid not in passages:
            rejected.append(EvidenceRejection(passage_id=pid or None, reason="unknown_passage"))
            continue
        if not quote or not claim:
            rejected.append(EvidenceRejection(passage_id=pid, reason="empty"))
            continue
        if len(quote) > MAX_QUOTE_CHARS or not quote_in_passage(quote, passages[pid].text):
            rejected.append(EvidenceRejection(passage_id=pid, reason="quote_not_found"))
            continue
        crit_ids = [c for c in dict.fromkeys(item.get("criterion_ids") or []) if c in criteria]
        if not crit_ids:
            rejected.append(EvidenceRejection(passage_id=pid, reason="unknown_criterion"))
            continue
        key = (pid, normalize_for_match(quote))
        if key in seen:
            rejected.append(EvidenceRejection(passage_id=pid, reason="duplicate"))
            continue
        source_id = pid.split(".")[0]
        if len(existing) + len(accepted) >= MAX_EVIDENCE_PER_RUN or per_source[source_id] >= MAX_EVIDENCE_PER_SOURCE:
            rejected.append(EvidenceRejection(passage_id=pid, reason="limit"))
            continue
        entity = canonical_entity(item.get("entity"), known_entities)
        source = sources[source_id]
        polarity = item.get("polarity") if item.get("polarity") in ("supports", "contradicts") else "supports"
        accepted.append(
            Evidence(
                id=f"E{next_n}",
                source_id=source_id,
                passage_id=pid,
                quote=quote,
                claim=claim,
                criterion_ids=crit_ids,
                entity=entity,
                polarity=polarity,
                first_party=is_first_party(source.url, entity),
                round=round_no,
            )
        )
        seen.add(key)
        per_source[source_id] += 1
        next_n += 1
    return EvidenceBatch(accepted, rejected)


# ---------------------------------------------------------------------------
# Coverage


def source_is_fresh(source: Source, freshness_days: int | None, today: date) -> bool | None:
    """True/False when the source date is known; None when undated."""
    published = parse_date(source.published_at)
    if published is None:
        return None
    if freshness_days is None:
        return True
    return published >= today - timedelta(days=freshness_days)


def _required_entities(plan: ResearchPlan) -> list[str]:
    if plan.task_type == TaskType.comparison:
        return list(plan.candidate_entities)
    return []


def compute_coverage(
    plan: ResearchPlan,
    evidence: list[Evidence],
    sources: dict[str, Source],
    *,
    today: date,
    extra_conflicts: list[Conflict] | None = None,
) -> list[CriterionCoverage]:
    by_criterion: dict[str, list[Evidence]] = defaultdict(list)
    for e in evidence:
        for cid in e.criterion_ids:
            by_criterion[cid].append(e)
    conflicted = {cid for c in extra_conflicts or [] for cid in c.criterion_ids}
    entities = _required_entities(plan)
    out: list[CriterionCoverage] = []
    for crit in plan.criteria:
        ev = by_criterion.get(crit.id, [])
        supporting = [e for e in ev if e.polarity == "supports"]
        domains = {registrable_domain(sources[e.source_id].url) for e in ev}
        status = CoverageStatus.supported
        note = None
        if not ev:
            status, note = CoverageStatus.missing, "No evidence found in reviewed sources."
        else:
            # Opposite polarity about the same entity is a conflict.
            polarity_by_entity: dict[str | None, set[str]] = defaultdict(set)
            for e in ev:
                polarity_by_entity[e.entity].add(e.polarity)
            if crit.id in conflicted or any(len(p) > 1 for p in polarity_by_entity.values()):
                status, note = CoverageStatus.conflicting, "Sources disagree."
            elif not supporting:
                status, note = CoverageStatus.weak, "Only contradicting evidence was found."
            else:
                independent = [e for e in supporting if not e.first_party]
                if crit.comparative and not independent:
                    status, note = CoverageStatus.weak, "Only first-party sources support this comparative criterion."
                elif all(sources[e.source_id].tier == SourceTier.low for e in supporting):
                    status, note = CoverageStatus.weak, "Only low-suitability sources (aggregators, forums, listicles)."
                elif crit.kind == CriterionKind.dimension and entities:
                    covered = {e.entity for e in supporting}
                    missing = [name for name in entities if name not in covered]
                    if missing:
                        status, note = CoverageStatus.weak, "No evidence for: " + ", ".join(missing) + "."
                elif plan.task_type == TaskType.entity_discovery and crit.kind == CriterionKind.eligibility:
                    found = {e.entity for e in supporting if e.entity}
                    target = plan.target_entity_count or 1
                    if len(found) < target:
                        status, note = CoverageStatus.weak, f"Evidence for {len(found)} of {target} requested entities."
                if status == CoverageStatus.supported and crit.needs_freshness:
                    freshness = [source_is_fresh(sources[e.source_id], plan.freshness_days, today) for e in supporting]
                    if not any(f is True for f in freshness):
                        window = f"{plan.freshness_days} days" if plan.freshness_days else "the freshness window"
                        status, note = CoverageStatus.stale, f"No supporting source is dated within {window}."
        out.append(
            CriterionCoverage(
                criterion_id=crit.id,
                description=crit.description,
                kind=crit.kind,
                required=crit.required,
                status=status,
                evidence_ids=[e.id for e in ev],
                independent_sources=len(domains),
                note=note,
            )
        )
    return out


def gap_criteria(coverage: list[CriterionCoverage]) -> list[CriterionCoverage]:
    return [c for c in coverage if c.status != CoverageStatus.supported]


def required_satisfied(coverage: list[CriterionCoverage]) -> bool:
    return all(c.status == CoverageStatus.supported for c in coverage if c.required)


def polarity_conflicts(evidence: list[Evidence]) -> list[Conflict]:
    """Deterministic conflicts: supporting and contradicting evidence for the same criterion and entity."""
    groups: dict[tuple[str, str | None], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for e in evidence:
        for cid in e.criterion_ids:
            groups[(cid, e.entity)][e.polarity].append(e.id)
    conflicts = []
    for (cid, entity), pol in groups.items():
        if pol.get("supports") and pol.get("contradicts"):
            who = f" about {entity}" if entity else ""
            conflicts.append(
                Conflict(
                    description=f"Sources disagree on {cid}{who}.",
                    criterion_ids=[cid],
                    evidence_ids=pol["supports"][:3] + pol["contradicts"][:3],
                    entity=entity,
                )
            )
    return conflicts


# ---------------------------------------------------------------------------
# Synthesis draft


@dataclass
class Draft:
    short_answer: CheckedText
    findings: list[Finding] = field(default_factory=list)
    comparison: ComparisonTable | None = None
    entities: list[EntityResult] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    return " ".join(str(value or "").split())[:limit]


def _ids(values: Any) -> list[str]:
    return [str(v) for v in dict.fromkeys(values or []) if isinstance(v, str)][:12]


# "(E3, E7)" or "[E1; E4]" written into prose despite the instructions.
INLINE_CITATION_RE = re.compile(r"\s*[(\[]\s*(E\d{1,4}(?:\s*[,;]\s*E\d{1,4})*)\s*[)\]]")


def _cited_text(item: dict[str, Any], limit: int = MAX_TEXT_CHARS) -> tuple[str, list[str]]:
    """Text and evidence ids of a drafted statement, with inline citation markers moved into the ids."""
    raw = " ".join(str(item.get("text") or "").split())
    inline = [i for m in INLINE_CITATION_RE.finditer(raw) for i in re.split(r"\s*[,;]\s*", m.group(1))]
    text = INLINE_CITATION_RE.sub("", raw).strip()[:limit]
    return text, _ids(list(item.get("evidence_ids") or []) + inline)


def parse_draft(data: dict[str, Any], plan: ResearchPlan) -> Draft:
    """Turn synthesis output into report structures. References are checked separately."""
    crit_ids = {c.id for c in plan.criteria}
    text, ids = _cited_text(data.get("short_answer") or {})
    draft = Draft(short_answer=CheckedText(text=text, evidence_ids=ids))
    for f in (data.get("key_findings") or [])[:10]:
        text, ids = _cited_text(f)
        if not text:
            continue
        kind = f.get("kind") if f.get("kind") in {k.value for k in ClaimKind} else ClaimKind.fact
        draft.findings.append(
            Finding(
                text=text,
                kind=kind,
                criterion_ids=[c for c in _ids(f.get("criterion_ids")) if c in crit_ids],
                evidence_ids=ids,
            )
        )
    table = data.get("comparison")
    # Discovery questions ("compare the top three X") get a table too: the options are the entities found.
    if isinstance(table, dict) and plan.task_type in (TaskType.comparison, TaskType.entity_discovery):
        columns = [c for c in _ids(table.get("criteria")) if c in crit_ids]
        rows = []
        for row in (table.get("rows") or [])[:8]:
            entity = canonical_entity(row.get("entity"), plan.candidate_entities)
            if not entity:
                continue
            cells = []
            for cell in row.get("cells") or []:
                cid = cell.get("criterion_id")
                if cid not in columns:
                    continue
                text, ids = _cited_text(cell, 600)
                unknown = bool(cell.get("unknown")) or not ids
                cells.append(
                    ComparisonCell(
                        criterion_id=cid,
                        text=text or "Not found in reviewed sources",
                        evidence_ids=[] if unknown else ids,
                        unknown=unknown,
                    )
                )
            have = {c.criterion_id for c in cells}
            cells += [
                ComparisonCell(criterion_id=cid, text="Not found in reviewed sources", unknown=True)
                for cid in columns
                if cid not in have
            ]
            cells.sort(key=lambda c: columns.index(c.criterion_id))
            rows.append(ComparisonRow(entity=entity, cells=cells))
        if columns and rows:
            draft.comparison = ComparisonTable(criteria=columns, rows=rows)
    for ent in (data.get("entities") or [])[:15]:
        name = _text(ent.get("name"), 80)
        if not name:
            continue
        summary = ent.get("summary")
        summary_text, summary_ids = _cited_text(summary) if isinstance(summary, dict) else ("", [])
        checks = []
        for chk in ent.get("eligibility") or []:
            if chk.get("criterion_id") not in crit_ids:
                continue
            status = chk.get("status") if chk.get("status") in {s.value for s in EligibilityStatus} else EligibilityStatus.unknown
            text, ids = _cited_text(chk, 600)
            checks.append(EligibilityCheck(criterion_id=chk["criterion_id"], status=status, text=text, evidence_ids=ids))
        draft.entities.append(
            EntityResult(
                name=name,
                included=bool(ent.get("included")),
                summary=CheckedText(text=summary_text, evidence_ids=summary_ids) if summary_text else None,
                eligibility=checks,
                exclusion_reason=_text(ent.get("exclusion_reason"), 300) or None,
            )
        )
    for c in (data.get("conflicts") or [])[:8]:
        desc = _text(c.get("description"), 600)
        if desc:
            draft.conflicts.append(
                Conflict(
                    description=desc,
                    criterion_ids=[x for x in _ids(c.get("criterion_ids")) if x in crit_ids],
                    evidence_ids=_ids(c.get("evidence_ids")),
                    entity=_text(c.get("entity"), 80) or None,
                    resolution=_text(c.get("resolution"), 600) or None,
                )
            )
    draft.limitations = [t for t in (_text(x, 400) for x in (data.get("limitations") or [])[:8]) if t]
    draft.next_steps = [t for t in (_text(x, 400) for x in (data.get("next_steps") or [])[:6]) if t]
    return draft


# ---------------------------------------------------------------------------
# Claims ledger


@dataclass
class ClaimRef:
    claim: Claim
    target: CheckedText


def enumerate_claims(draft: Draft) -> list[ClaimRef]:
    """Assign C# ids to every checkable statement in the draft."""
    refs: list[ClaimRef] = []

    def add(target: CheckedText, location: ClaimLocation, kind: ClaimKind) -> None:
        cid = f"C{len(refs) + 1}"
        target.claim_id = cid
        refs.append(
            ClaimRef(
                Claim(id=cid, location=location, kind=kind, text=target.text, evidence_ids=list(target.evidence_ids)),
                target,
            )
        )

    if draft.short_answer.text:
        add(draft.short_answer, ClaimLocation.short_answer, ClaimKind.interpretation)
    for f in draft.findings:
        add(f, ClaimLocation.finding, f.kind)
    if draft.comparison:
        for row in draft.comparison.rows:
            for cell in row.cells:
                if not cell.unknown:
                    add(cell, ClaimLocation.comparison_cell, ClaimKind.fact)
    for ent in draft.entities:
        if ent.summary:
            add(ent.summary, ClaimLocation.entity, ClaimKind.fact)
        for chk in ent.eligibility:
            if chk.status != EligibilityStatus.unknown:
                add(chk, ClaimLocation.eligibility, ClaimKind.fact)
    return refs


def check_references(refs: list[ClaimRef], evidence_ids: set[str]) -> int:
    """Reference check: drop citations to evidence that does not exist.

    Claims left without any valid citation are marked not_supported before the
    semantic check runs. Returns the number of invalid references removed.
    """
    removed = 0
    for ref in refs:
        valid = [e for e in ref.target.evidence_ids if e in evidence_ids and EVIDENCE_ID_RE.match(e)]
        removed += len(ref.target.evidence_ids) - len(valid)
        ref.target.evidence_ids = valid
        ref.claim.evidence_ids = list(valid)
        if not valid:
            ref.claim.verdict = SupportVerdict.not_supported
            ref.claim.issue = "No valid evidence cited."
            ref.target.verdict = SupportVerdict.not_supported
    return removed


def apply_verdict(ref: ClaimRef, verdict: SupportVerdict, issue: str | None) -> None:
    ref.claim.verdict = verdict
    ref.claim.issue = issue
    ref.target.verdict = verdict
    if verdict == SupportVerdict.supported:
        ref.target.disposition = ClaimDisposition.kept
        ref.target.note = None
    elif verdict == SupportVerdict.partially_supported:
        ref.target.disposition = ClaimDisposition.qualified
        ref.target.note = f"Partially supported: {issue}" if issue else "Partially supported by the cited evidence."
    elif verdict == SupportVerdict.not_supported:
        ref.target.disposition = ClaimDisposition.removed
        ref.target.note = issue
    else:
        ref.target.disposition = ClaimDisposition.qualified
        ref.target.note = "Not verified: the verification step could not run."


def finalize_draft(draft: Draft) -> list[str]:
    """Remove claims marked `removed` from the report. Returns the removed texts."""
    removed: list[str] = []
    sa = draft.short_answer
    if sa.disposition == ClaimDisposition.removed or not sa.text:
        if sa.text:
            removed.append(sa.text)
        draft.short_answer = CheckedText(
            text="No short answer could be verified against the collected evidence. See the verified findings and coverage below.",
            evidence_ids=[],
            verdict=SupportVerdict.unchecked,
            disposition=ClaimDisposition.qualified,
            note="Replaced because the drafted answer was not supported by its citations.",
        )
    kept = []
    for f in draft.findings:
        if f.disposition == ClaimDisposition.removed:
            removed.append(f.text)
        else:
            kept.append(f)
    draft.findings = kept
    if draft.comparison:
        for row in draft.comparison.rows:
            for i, cell in enumerate(row.cells):
                if cell.disposition == ClaimDisposition.removed:
                    removed.append(f"{row.entity}: {cell.text}")
                    row.cells[i] = ComparisonCell(
                        criterion_id=cell.criterion_id,
                        text="Not verified in reviewed sources",
                        unknown=True,
                        claim_id=cell.claim_id,
                        verdict=cell.verdict,
                        disposition=ClaimDisposition.removed,
                        note=cell.note,
                    )
    for ent in draft.entities:
        if ent.summary and ent.summary.disposition == ClaimDisposition.removed:
            removed.append(f"{ent.name}: {ent.summary.text}")
            ent.summary = None
        for chk in ent.eligibility:
            if chk.disposition == ClaimDisposition.removed:
                removed.append(f"{ent.name}: {chk.text}")
                chk.status = EligibilityStatus.unknown
                chk.text = "Not verified in reviewed sources"
                chk.evidence_ids = []
        if ent.included and any(chk.status != EligibilityStatus.met for chk in ent.eligibility):
            ent.included = False
            ent.exclusion_reason = ent.exclusion_reason or "Eligibility not confirmed by verified evidence."
    if draft.comparison and draft.entities:
        # In discovery runs the table compares only the entities that made the list.
        included = [e.name for e in draft.entities if e.included]
        draft.comparison.rows = [r for r in draft.comparison.rows if canonical_entity(r.entity, included) in included]
        if not draft.comparison.rows:
            draft.comparison = None
    return removed


def keep_valid_conflicts(conflicts: list[Conflict], evidence_ids: set[str]) -> list[Conflict]:
    out = []
    for c in conflicts:
        ids = [e for e in c.evidence_ids if e in evidence_ids]
        if ids:
            out.append(c.model_copy(update={"evidence_ids": ids}))
    return out


# ---------------------------------------------------------------------------
# Status and confidence


def decide_status(
    *,
    coverage: list[CriterionCoverage],
    refs: list[ClaimRef],
    verification_ran: bool,
    evidence_count: int,
    hit_limit: bool,
) -> RunStatus:
    supported_claims = [r for r in refs if r.claim.verdict in (SupportVerdict.supported, SupportVerdict.partially_supported)]
    if evidence_count == 0 or (verification_ran and not supported_claims):
        return RunStatus.insufficient_evidence
    # A report whose short answer failed verification and whose required criteria all lack support has
    # not answered anything, even if a caveat-style finding survived; that is insufficient evidence.
    answer = next((r for r in refs if r.claim.location == ClaimLocation.short_answer), None)
    answer_failed = answer is None or answer.claim.verdict == SupportVerdict.not_supported
    required = [c for c in coverage if c.required] or coverage
    if verification_ran and answer_failed and not any(c.status == CoverageStatus.supported for c in required):
        return RunStatus.insufficient_evidence
    if verification_ran and required_satisfied(coverage) and not hit_limit:
        return RunStatus.completed
    return RunStatus.partial


def assess_confidence(
    *,
    status: RunStatus,
    coverage: list[CriterionCoverage],
    refs: list[ClaimRef],
    evidence: list[Evidence],
    sources: dict[str, Source],
    conflicts: list[Conflict],
    verification_ran: bool,
) -> ConfidenceAssessment:
    """Deterministic High/Medium/Low rubric (documented in README and docs/evaluation.md)."""
    required = [c for c in coverage if c.required] or coverage
    req_supported = sum(1 for c in required if c.status == CoverageStatus.supported)
    req_rate = req_supported / len(required) if required else 0.0
    judged = [r for r in refs if r.claim.verdict != SupportVerdict.unchecked]
    supported = sum(1 for r in judged if r.claim.verdict == SupportVerdict.supported)
    support_rate = supported / len(judged) if judged else 0.0
    cited_sources = {e.source_id for e in evidence}
    domains = {registrable_domain(sources[s].url) for s in cited_sources if s in sources}
    high_tier = sum(1 for s in cited_sources if sources[s].tier == SourceTier.high)
    first_party_share = (sum(1 for e in evidence if e.first_party) / len(evidence)) if evidence else 0.0
    unresolved_conflicts = [c for c in conflicts if not c.resolution]
    stale = sum(1 for c in required if c.status == CoverageStatus.stale)
    weak = sum(1 for c in required if c.status == CoverageStatus.weak)

    factors: dict[str, str | float | int] = {
        "required_criteria_supported": f"{req_supported}/{len(required)}",
        "claim_support_rate": round(support_rate, 2),
        "independent_domains": len(domains),
        "high_suitability_sources": high_tier,
        "first_party_evidence_share": round(first_party_share, 2),
        "unresolved_conflicts": len(unresolved_conflicts),
        "stale_required_criteria": stale,
        "weak_required_criteria": weak,
        "verification": "ran" if verification_ran else "did not run",
    }

    if (
        status in (RunStatus.failed, RunStatus.insufficient_evidence, RunStatus.cancelled, RunStatus.interrupted)
        or not verification_ran
    ):
        level = Confidence.low
    elif (
        status == RunStatus.completed
        and req_rate == 1.0
        and support_rate >= 0.9
        and len(domains) >= 3
        and not unresolved_conflicts
        and stale == 0
        and first_party_share <= 0.5
    ):
        level = Confidence.high
    elif req_rate >= 0.6 and support_rate >= 0.75 and len(domains) >= 2:
        level = Confidence.medium
    else:
        level = Confidence.low

    reasons = [
        f"{req_supported} of {len(required)} required criteria are supported",
        f"{supported} of {len(judged)} checked claims are fully supported" if judged else "no claims could be checked",
        f"evidence comes from {len(domains)} independent site{'s' if len(domains) != 1 else ''}",
    ]
    if unresolved_conflicts:
        reasons.append(f"{len(unresolved_conflicts)} unresolved conflict{'s' if len(unresolved_conflicts) != 1 else ''}")
    if stale:
        reasons.append(f"{stale} required criteri{'a are' if stale != 1 else 'on is'} supported only by old or undated sources")
    if weak:
        reasons.append(f"{weak} required criteri{'a have' if weak != 1 else 'on has'} only weak evidence")
    if first_party_share > 0.5:
        reasons.append("most evidence is first-party (vendor or company) material")
    if not verification_ran:
        reasons.append("claim verification did not run")
    explanation = f"{level.value.capitalize()}: " + "; ".join(reasons) + "."
    return ConfidenceAssessment(level=level, explanation=explanation, factors=factors)


def read_sources(sources: dict[str, Source]) -> list[Source]:
    return [s for s in sources.values() if s.state == SourceState.read]
