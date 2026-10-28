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


LEGAL_SUFFIXES = frozenset({"inc", "ltd", "limited", "llc", "pvt", "corp", "corporation", "co", "gmbh", "plc", "sa", "ag", "bv"})


def _alias_token(name: str) -> str:
    """Normalized name with trailing legal-form words removed ("Keka Technologies Pvt Ltd" -> "kekatechnologies")."""
    words = [entity_token(w) for w in name.replace(",", " ").replace(".", " ").split()]
    words = [w for w in words if w]
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return "".join(words)


def canonical_entity(name: str | None, known: list[str]) -> str | None:
    """Map a name to a known entity only when the names are the same after normalization.

    Normalization lowercases, drops punctuation, and removes trailing legal-form words. Nothing
    looser: "Kekatech" is not "Keka", "Milvus Lite" is not "Milvus", and "Zoho People" is kept
    distinct from "Zoho". Different names stay separate entities with their own provenance.
    """
    if not name or not name.strip():
        return None
    name = " ".join(name.split())[:80]
    token = _alias_token(name)
    for k in known:
        kt = _alias_token(k)
        if kt and kt == token:
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


MAX_NAMED_ENTITIES = 6


def _names(entities: list[str]) -> str:
    shown = entities[:MAX_NAMED_ENTITIES]
    more = f" and {len(entities) - MAX_NAMED_ENTITIES} more" if len(entities) > MAX_NAMED_ENTITIES else ""
    return ", ".join(shown) + more


def compute_coverage(
    plan: ResearchPlan,
    evidence: list[Evidence],
    sources: dict[str, Source],
    *,
    today: date,
    extra_conflicts: list[Conflict] | None = None,
) -> list[CriterionCoverage]:
    """Per-criterion coverage. For comparisons and discovery it is judged per entity: evidence for one
    candidate never satisfies, or freshens, another candidate's requirement."""
    by_criterion: dict[str, list[Evidence]] = defaultdict(list)
    for e in evidence:
        for cid in e.criterion_ids:
            by_criterion[cid].append(e)
    conflicted = {cid for c in extra_conflicts or [] for cid in c.criterion_ids}
    entities = _required_entities(plan)
    # Discovery: every entity seen in any evidence is a candidate whose eligibility must be established.
    seen_entities = list(dict.fromkeys([*plan.candidate_entities, *(e.entity for e in evidence if e.entity)]))
    out: list[CriterionCoverage] = []
    for crit in plan.criteria:
        ev = by_criterion.get(crit.id, [])
        supporting = [e for e in ev if e.polarity == "supports"]
        domains = {registrable_domain(sources[e.source_id].url) for e in ev}
        status = CoverageStatus.supported
        note = None
        missing_entities: list[str] = []
        stale_entities: list[str] = []
        if not ev:
            status, note = CoverageStatus.missing, "No evidence found in reviewed sources."
            if crit.kind == CriterionKind.dimension and entities:
                missing_entities = list(entities)
            elif plan.task_type == TaskType.entity_discovery and crit.kind == CriterionKind.eligibility:
                missing_entities = list(seen_entities)
            if missing_entities:
                note = "Not established for: " + _names(missing_entities) + "."
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
                    missing_entities = [name for name in entities if name not in covered]
                    if missing_entities:
                        status, note = CoverageStatus.weak, "Not established for: " + _names(missing_entities) + "."
                elif plan.task_type == TaskType.entity_discovery and crit.kind == CriterionKind.eligibility:
                    found = {e.entity for e in supporting if e.entity}
                    missing_entities = [name for name in seen_entities if name not in found]
                    target = plan.target_entity_count or 1
                    if len(found) < target:
                        status = CoverageStatus.weak
                        note = f"Established for {len(found)} of {target} requested entities."
                        if missing_entities:
                            note += " Not established for: " + _names(missing_entities) + "."
                if status == CoverageStatus.supported and crit.needs_freshness:
                    window = f"{plan.freshness_days} days" if plan.freshness_days else "the freshness window"
                    per_entity = crit.kind == CriterionKind.dimension and entities
                    groups = (
                        {name: [e for e in supporting if e.entity == name] for name in entities}
                        if per_entity
                        else {None: supporting}
                    )
                    for name, group in groups.items():
                        fresh = [source_is_fresh(sources[e.source_id], plan.freshness_days, today) for e in group]
                        if group and not any(f is True for f in fresh):
                            stale_entities.append(name or "")
                    if stale_entities:
                        status = CoverageStatus.stale
                        if per_entity:
                            note = f"No source dated within {window} for: " + _names(stale_entities) + "."
                        else:
                            note, stale_entities = f"No supporting source is dated within {window}.", []
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
                missing_entities=missing_entities[:20],
                stale_entities=stale_entities[:20],
            )
        )
    return out


def gap_criteria(coverage: list[CriterionCoverage]) -> list[CriterionCoverage]:
    return [c for c in coverage if c.status != CoverageStatus.supported]


def required_satisfied(coverage: list[CriterionCoverage]) -> bool:
    """True only when there is at least one required criterion and every required criterion is supported."""
    required = [c for c in coverage if c.required]
    return bool(required) and all(c.status == CoverageStatus.supported for c in required)


def _side(e: Evidence, sources: dict[str, Source] | None) -> str:
    src = sources.get(e.source_id) if sources else None
    where = f"{src.domain}" if src else e.source_id
    dated = f", dated {src.published_at}" if src and src.published_at else ", undated"
    claim = e.claim.rstrip(".")
    return f"{claim} ({e.id}, {where}{dated})"


def polarity_conflicts(
    evidence: list[Evidence],
    sources: dict[str, Source] | None = None,
    criteria: dict[str, Criterion] | None = None,
) -> list[Conflict]:
    """Possible conflicts detected by code: supporting and contradicting evidence for the same criterion and entity.

    The description quotes each side's claim with its citation and date so the reader can judge the
    disagreement. These are flagged `review_needed`: the code checks that both sides address the same
    entity and criterion, not that they address the same version, period, or workload.
    """
    groups: dict[tuple[str, str | None], dict[str, list[Evidence]]] = defaultdict(lambda: defaultdict(list))
    for e in evidence:
        for cid in e.criterion_ids:
            groups[(cid, e.entity)][e.polarity].append(e)
    conflicts = []
    for (cid, entity), pol in groups.items():
        if pol.get("supports") and pol.get("contradicts"):
            crit = criteria.get(cid) if criteria else None
            topic = crit.description if crit else cid
            who = f" for {entity}" if entity else ""
            pro, con = pol["supports"][:2], pol["contradicts"][:2]
            description = (
                f'Possible conflict on "{topic}"{who}. One side: '
                + "; ".join(_side(e, sources) for e in pro)
                + ". The other side: "
                + "; ".join(_side(e, sources) for e in con)
                + ". The passages may describe different versions, dates, or conditions; read both before relying on either."
            )
            conflicts.append(
                Conflict(
                    description=description[:900],
                    criterion_ids=[cid],
                    evidence_ids=[e.id for e in pol["supports"][:3]] + [e.id for e in pol["contradicts"][:3]],
                    entity=entity,
                    review_needed=True,
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


def finalize_draft(draft: Draft, eligibility_ids: list[str] | None = None) -> list[str]:
    """Remove claims marked `removed` from the report. Returns the removed texts.

    `eligibility_ids` are the plan's eligibility criteria: an entity stays included only when every one
    of them is present and met for that entity, so a missing check cannot pass as a met one.
    """
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
        if ent.included and eligibility_ids:
            met = {chk.criterion_id for chk in ent.eligibility if chk.status == EligibilityStatus.met}
            unchecked = [cid for cid in eligibility_ids if cid not in met]
            if unchecked:
                ent.included = False
                ent.exclusion_reason = "Eligibility not established for: " + ", ".join(unchecked) + "."
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
    criteria: list[Criterion] | None = None,
) -> ConfidenceAssessment:
    """Deterministic High/Medium/Low rubric built from the evidence the final claims actually cite.

    Only evidence cited by a claim that survived verification counts. Retrieved-but-uncited pages
    cannot raise confidence, a copy of a cited page is not a second source, and a comparative
    criterion needs independent (non-first-party) cited evidence. One authoritative primary source
    can establish a narrow documented fact; a comparison needs more than one site. The rubric is
    documented in docs/evaluation.md; it is not calibrated and shows no probabilities.
    """
    required = [c for c in coverage if c.required] or coverage
    req_supported = sum(1 for c in required if c.status == CoverageStatus.supported)
    req_rate = req_supported / len(required) if required else 0.0
    stale = sum(1 for c in required if c.status == CoverageStatus.stale)
    weak = sum(1 for c in required if c.status == CoverageStatus.weak)
    unresolved_conflicts = [c for c in conflicts if not c.resolution]

    kept = [r for r in refs if r.target.disposition != ClaimDisposition.removed]
    removed_count = len(refs) - len(kept)
    judged = [r for r in kept if r.claim.verdict != SupportVerdict.unchecked]
    supported = sum(1 for r in judged if r.claim.verdict == SupportVerdict.supported)
    support_rate = supported / len(judged) if judged else 0.0
    answer = next((r for r in refs if r.claim.location == ClaimLocation.short_answer), None)
    answer_supported = (
        answer is not None
        and answer.target.disposition != ClaimDisposition.removed
        and answer.claim.verdict in (SupportVerdict.supported, SupportVerdict.partially_supported)
        and bool(answer.target.evidence_ids)
    )

    cited_ids = {eid for r in kept for eid in r.target.evidence_ids}
    cited = [e for e in evidence if e.id in cited_ids]
    cited_source_ids = {e.source_id for e in cited if e.source_id in sources}
    # Provenance: one site per registrable domain, and copies of the same content count once.
    hashes: set[str] = set()
    domains: set[str] = set()
    for sid in cited_source_ids:
        src = sources[sid]
        if src.content_hash and src.content_hash in hashes:
            continue
        if src.content_hash:
            hashes.add(src.content_hash)
        domains.add(registrable_domain(src.url))
    high_tier_cited = sum(1 for sid in cited_source_ids if sources[sid].tier == SourceTier.high)
    first_party_share = (sum(1 for e in cited if e.first_party) / len(cited)) if cited else 0.0
    by_criterion: dict[str, list[Evidence]] = defaultdict(list)
    for e in cited:
        for cid in e.criterion_ids:
            by_criterion[cid].append(e)
    crit_map = {c.id: c for c in criteria or []}
    comparative_required = [c for c in required if crit_map.get(c.criterion_id) and crit_map[c.criterion_id].comparative]
    comparative_without_independent = [
        c.criterion_id for c in comparative_required if not any(not e.first_party for e in by_criterion.get(c.criterion_id, []))
    ]
    # A narrow documented fact: nothing comparative, nothing per-entity, and an authoritative cited source.
    narrow_fact = (
        not comparative_required
        and all(
            crit_map.get(c.criterion_id) is None or crit_map[c.criterion_id].kind != CriterionKind.dimension for c in required
        )
        and high_tier_cited >= 1
    )
    material_removal = (answer is not None and answer.target.disposition == ClaimDisposition.removed) or (
        refs and removed_count / len(refs) > 0.25
    )

    factors: dict[str, str | float | int] = {
        "required_criteria_supported": f"{req_supported}/{len(required)}",
        "claim_support_rate": round(support_rate, 2),
        "claims_kept": len(kept),
        "claims_removed": removed_count,
        "short_answer_supported": "yes" if answer_supported else "no",
        "cited_evidence": len(cited),
        "independent_domains": len(domains),
        "high_suitability_sources": high_tier_cited,
        "first_party_evidence_share": round(first_party_share, 2),
        "comparative_criteria_without_independent_evidence": len(comparative_without_independent),
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
        and answer_supported
        and not unresolved_conflicts
        and stale == 0
        and not comparative_without_independent
        and not material_removal
        and (len(domains) >= 2 or narrow_fact)
    ):
        level = Confidence.high
    elif req_rate >= 0.6 and support_rate >= 0.75 and len(domains) >= 1 and (answer_supported or supported >= 1):
        level = Confidence.medium
    else:
        level = Confidence.low

    reasons = [
        f"{req_supported} of {len(required)} required criteria are supported",
        f"{supported} of {len(judged)} kept claims are fully supported" if judged else "no claims could be checked",
        f"the kept claims cite {len(cited)} passage{'s' if len(cited) != 1 else ''} from {len(domains)} independent site{'s' if len(domains) != 1 else ''}",
    ]
    if not answer_supported and answer is not None:
        reasons.append("the short answer was not supported by its citations")
    if removed_count:
        reasons.append(f"{removed_count} claim{'s were' if removed_count != 1 else ' was'} removed as unsupported")
    if unresolved_conflicts:
        reasons.append(f"{len(unresolved_conflicts)} unresolved conflict{'s' if len(unresolved_conflicts) != 1 else ''}")
    if stale:
        reasons.append(f"{stale} required criteri{'a are' if stale != 1 else 'on is'} supported only by old or undated sources")
    if weak:
        reasons.append(f"{weak} required criteri{'a have' if weak != 1 else 'on has'} only weak evidence")
    if comparative_without_independent:
        reasons.append(
            f"{len(comparative_without_independent)} comparative criteri{'a lack' if len(comparative_without_independent) != 1 else 'on lacks'} independent (non-vendor) evidence"
        )
    if level == Confidence.high and narrow_fact and len(domains) < 2:
        reasons.append("a single authoritative source establishes a narrow documented fact")
    if not verification_ran:
        reasons.append("claim verification did not run")
    explanation = f"{level.value.capitalize()}: " + "; ".join(reasons) + "."
    return ConfidenceAssessment(level=level, explanation=explanation, factors=factors)


def read_sources(sources: dict[str, Source]) -> list[Source]:
    return [s for s in sources.values() if s.state == SourceState.read]
