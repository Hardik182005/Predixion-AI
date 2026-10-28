"""Markdown export of a research report.

Everything that came from the web or the model (titles, quotes, claims) is
untrusted. It is escaped so it cannot inject links, images, HTML, or table
structure into the exported document. Citations render as [E#] and point to
the evidence list at the end.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .contracts import CheckedText, ClaimDisposition, ResearchReport, SupportVerdict

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>!|~])")
_LINE_START = re.compile(r"^([#+\-=]|\d+[.)])")

STATUS_LABEL = {
    "completed": "Completed",
    "partial": "Partial answer",
    "insufficient_evidence": "Insufficient evidence",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "interrupted": "Interrupted",
}


def esc(text: str | None) -> str:
    """Escape untrusted text for inline Markdown: one line, no active syntax."""
    if not text:
        return ""
    one_line = _MD_SPECIAL.sub(r"\\\1", " ".join(text.split()))
    # Escape what would start a heading or list when the text begins a line.
    return _LINE_START.sub(lambda m: "\\" + m.group(0), one_line)


def safe_url(url: str) -> str:
    if not url.lower().startswith(("https://", "http://")):
        return ""
    return quote(url, safe=":/?#[]@!$&'*+,;=%-._~")


def _cites(ids: list[str]) -> str:
    return " " + " ".join(f"[{esc(i)}]" for i in ids) if ids else ""


def _qualifier(item: CheckedText) -> str:
    if item.verdict == SupportVerdict.unchecked:
        return " *(not verified)*"
    if item.disposition == ClaimDisposition.qualified or item.verdict == SupportVerdict.partially_supported:
        return " *(qualified)*"
    return ""


def render_markdown(report: ResearchReport) -> str:
    out: list[str] = []
    ex = report.execution
    out.append(f"# {esc(report.question)}")
    out.append("")
    meta = [
        f"**Status:** {STATUS_LABEL.get(report.status.value, report.status.value)}",
        f"**Mode:** {ex.mode.value}",
        f"**Model:** {esc(ex.model)}",
        f"**Created:** {report.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Run:** `{report.run_id}`",
    ]
    out.append(" · ".join(meta))
    if ex.mode.value == "fixture":
        out.append("")
        out.append("> Fixture demo: sources and documents are recorded test data, not live web results.")
    if report.stop_detail:
        out.append("")
        out.append(f"> Stopped: {esc(report.stop_detail)}")

    out += ["", "## Short answer", "", esc(report.short_answer.text) + _cites(report.short_answer.evidence_ids)]

    if report.key_findings:
        out += ["", "## Findings", ""]
        for f in report.key_findings:
            if f.disposition == ClaimDisposition.removed:
                continue
            kind = "" if f.kind.value == "fact" else f" *({f.kind.value})*"
            out.append(f"- {esc(f.text)}{_cites(f.evidence_ids)}{kind}{_qualifier(f)}")

    if report.comparison and report.comparison.rows:
        crit = {c.id: c.description for c in (report.plan.criteria if report.plan else [])}
        cols = report.comparison.criteria
        out += ["", "## Comparison", ""]
        out.append("| Option | " + " | ".join(esc(crit.get(c, c)) for c in cols) + " |")
        out.append("|---" * (len(cols) + 1) + "|")
        for row in report.comparison.rows:
            cells = {c.criterion_id: c for c in row.cells}
            values = []
            for cid in cols:
                cell = cells.get(cid)
                if cell is None or cell.unknown:
                    values.append("Not found in sources")
                else:
                    values.append(esc(cell.text) + _cites(cell.evidence_ids))
            out.append(f"| {esc(row.entity)} | " + " | ".join(values) + " |")

    if report.entities:
        included = [e for e in report.entities if e.included]
        excluded = [e for e in report.entities if not e.included]
        if included:
            out += ["", "## Entities", ""]
            for e in included:
                summary = e.summary
                line = f"- **{esc(e.name)}**"
                if summary:
                    line += f": {esc(summary.text)}{_cites(summary.evidence_ids)}"
                out.append(line)
        if excluded:
            out += ["", "### Considered and excluded", ""]
            for e in excluded:
                out.append(f"- {esc(e.name)}: {esc(e.exclusion_reason) or 'Did not meet the criteria.'}")

    if report.conflicts:
        out += ["", "## Conflicting evidence", ""]
        for c in report.conflicts:
            resolution = f" Resolution: {esc(c.resolution)}" if c.resolution else " Unresolved."
            out.append(f"- {esc(c.description)}{_cites(c.evidence_ids)}.{resolution}")

    out += ["", "## Coverage", "", "| Criterion | Status | Evidence |", "|---|---|---|"]
    for cov in report.coverage:
        req = "" if cov.required else " (optional)"
        out.append(
            f"| {esc(cov.criterion_id)}: {esc(cov.description)}{req} | {cov.status.value.replace('_', ' ')} | "
            f"{', '.join(esc(e) for e in cov.evidence_ids) or '-'} |"
        )

    conf = report.confidence
    out += ["", "## Confidence", "", f"**{conf.level.value.capitalize()}.** {esc(conf.explanation)}"]

    for title, items in (
        ("Limitations", report.limitations),
        ("Assumptions", report.assumptions),
        ("Next steps", report.next_steps),
    ):
        if items:
            out += ["", f"## {title}", ""]
            out += [f"- {esc(i)}" for i in items]

    sources = {s.id: s for s in report.sources}
    if report.evidence:
        out += ["", "## Evidence", ""]
        for e in report.evidence:
            src = sources.get(e.source_id)
            where = f"{esc(src.title) or esc(src.domain)} ({esc(src.domain)})" if src else esc(e.source_id)
            stance = " (contradicts)" if e.polarity == "contradicts" else ""
            out.append(f"- **[{esc(e.id)}]** {where}{stance}: “{esc(e.quote)}”")

    if report.sources:
        out += ["", "## Sources", ""]
        for s in report.sources:
            url = safe_url(s.url)
            link = f"<{url}>" if url else "(no link)"
            out.append(f"- **{esc(s.id)}** {esc(s.title) or esc(s.domain)} · {s.tier.value} · {link}")

    m = ex.metrics
    out += [
        "",
        "## Execution",
        "",
        f"- Rounds: {m.rounds}; searches: {m.search_calls}; pages read: {m.pages_read}; model calls: {m.model_calls}",
        f"- Tokens: {m.input_tokens} in / {m.output_tokens} out; estimated cost: ${m.estimated_cost_usd:.4f}"
        + (" (uncertain)" if m.cost_uncertain else ""),
        f"- Duration: {(m.duration_ms or 0) / 1000:.1f} s; prompt version {esc(ex.prompt_version)}",
        f"- Verification: {report.verification.supported}/{report.verification.claims_checked} claims supported",
        "",
    ]
    return "\n".join(out)
