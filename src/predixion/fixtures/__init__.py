"""Deterministic fixture providers for offline demos, tests, and regression evaluation.

Fixture mode never calls external services. Scenario files in `scenarios/`
hold synthetic pages on reserved `.example` domains, canned plans, and the
evidence statements a fixture "model" may extract. The fixture model is a
heuristic stand-in for the real model: it exercises the same contracts,
validation, verification, and repair paths, but its outputs are scripted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

from ..contracts import ExtractedPage, ItemFailure, SearchArgs, SearchHit
from ..llm import ModelOutcome
from ..prompts import Task, TaskSpec
from ..sources import normalize_for_match, tokenize
from ..tools import ExtractOutcome, SearchOutcome

FIXTURE_MODEL = "fixture-heuristic-v1"
SUPPORTED_RATIO = 0.6
PARTIAL_RATIO = 0.4
# Absolute or superlative wording the fixture verifier refuses unless the evidence uses it too.
UNSUPPORTED_MARKERS = (
    "fastest",
    "best",
    "always",
    "never",
    "every",
    "guarantees",
    "guaranteed",
    "most popular",
    "leading",
    "cheapest",
)


@dataclass
class Scenario:
    id: str
    question: str
    aliases: list[str]
    plan: dict[str, Any]
    queries: dict[str, str]
    documents: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    follow_up: list[dict[str, Any]] = field(default_factory=list)
    synthesis: dict[str, Any] = field(default_factory=dict)
    bad_extractions: list[dict[str, Any]] = field(default_factory=list)


def _norm_question(text: str) -> set[str]:
    return set(tokenize(text))


@lru_cache
def load_scenarios() -> dict[str, Scenario]:
    out = {}
    folder = resources.files(__package__).joinpath("scenarios")
    for entry in sorted(folder.iterdir(), key=lambda p: p.name):
        if not entry.name.endswith(".json"):
            continue
        raw = json.loads(entry.read_text(encoding="utf-8"))
        # Plan queries name a scenario query key so the canned search can match them exactly.
        for q in raw["plan"]["queries"]:
            if "key" in q:
                q["text"] = raw["queries"][q.pop("key")]
        facts = []
        for doc in raw["documents"]:
            for fact in doc.get("facts", []):
                facts.append({**fact, "url": doc["url"]})
        out[raw["id"]] = Scenario(
            id=raw["id"],
            question=raw["question"],
            aliases=raw.get("aliases", []),
            plan=raw["plan"],
            queries=raw["queries"],
            documents=raw["documents"],
            facts=facts,
            follow_up=raw.get("follow_up", []),
            synthesis=raw.get("synthesis", {}),
            bad_extractions=raw.get("bad_extractions", []),
        )
    return out


def match_scenario(question: str) -> Scenario | None:
    """The scenario whose question best matches, if the match is close."""
    q = _norm_question(question)
    if not q:
        return None
    best, best_score = None, 0.0
    for scenario in load_scenarios().values():
        for candidate in [scenario.question, *scenario.aliases]:
            c = _norm_question(candidate)
            score = len(q & c) / len(q | c) if c else 0.0
            if score > best_score:
                best, best_score = scenario, score
    return best if best_score >= 0.6 else None


def sample_questions() -> list[dict[str, str]]:
    return [{"id": s.id, "question": s.question} for s in load_scenarios().values()]


# ---------------------------------------------------------------------------
# Tools


class FixtureSearch:
    name = "fixture-search"

    def __init__(self, scenario: Scenario | None) -> None:
        self.scenario = scenario

    async def search(self, args: SearchArgs, *, timeout: float) -> SearchOutcome:
        del timeout
        if self.scenario is None:
            return SearchOutcome(hits=[], credits=0.0)
        key = next((k for k, text in self.scenario.queries.items() if _same_query(text, args.query)), None)
        if key is not None:
            docs = [d for d in self.scenario.documents if key in d.get("found_by", [])]
        else:
            # Unscripted query (e.g. rule-based follow-up): rank by keyword overlap.
            wanted = set(tokenize(args.query))
            scored = []
            for d in self.scenario.documents:
                have = set(tokenize(f"{d['title']} {d.get('snippet', '')}"))
                overlap = len(wanted & have) / max(1, len(wanted))
                if overlap >= 0.5:
                    scored.append((overlap, d))
            docs = [d for _, d in sorted(scored, key=lambda x: x[0], reverse=True)]
        hits = [
            SearchHit(
                url=d["url"],
                title=d["title"],
                snippet=d.get("snippet") or d["content"][:240],
                score=round(max(0.2, 0.92 - 0.06 * i), 3),
                published_date=d.get("published"),
            )
            for i, d in enumerate(docs[: args.max_results])
        ]
        return SearchOutcome(hits=hits, credits=0.0)


def _same_query(a: str, b: str) -> bool:
    return " ".join(a.casefold().split()) == " ".join(b.casefold().split())


class FixtureExtract:
    name = "fixture-extract"

    def __init__(self, scenario: Scenario | None) -> None:
        self.scenario = scenario

    async def extract(self, urls: list[str], *, timeout: float, query: str | None = None) -> ExtractOutcome:
        del timeout, query
        docs = {d["url"]: d for d in (self.scenario.documents if self.scenario else [])}
        pages, failures = [], []
        for url in urls:
            doc = docs.get(url)
            if doc is None:
                failures.append(ItemFailure(item=url, error="HTTP 404 (fixture: no such page)"))
            elif doc.get("fail"):
                failures.append(ItemFailure(item=url, error=str(doc["fail"])))
            else:
                pages.append(ExtractedPage(url=url, content=doc["content"]))
        return ExtractOutcome(pages=pages, failures=failures, credits=0.0)


# ---------------------------------------------------------------------------
# Model


class FixtureModel:
    """Scripted stand-in for the research model. Deterministic for a given scenario."""

    model = FIXTURE_MODEL
    sdk_version = None

    def __init__(self, scenario: Scenario | None) -> None:
        self.scenario = scenario

    async def generate(self, spec: TaskSpec, input_text: str, payload: dict[str, Any], *, timeout: float) -> ModelOutcome:
        del timeout
        handler = {
            Task.plan: self._plan,
            Task.extract: self._extract,
            Task.follow_up: self._follow_up,
            Task.synthesize: self._synthesize,
            Task.verify: self._verify,
            Task.repair: self._repair,
        }[spec.task]
        data = handler(payload)
        # Character-based token estimates; fixture runs have no billable usage.
        return ModelOutcome(data=data, input_tokens=len(input_text) // 4 + 300, output_tokens=len(json.dumps(data)) // 4)

    # -- plan ------------------------------------------------------------

    def _plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.scenario is not None:
            return self.scenario.plan
        question = str(payload.get("question") or "")
        return {
            "objective": question,
            "task_type": "explainer",
            "interpretation": f"Research the question as stated: {question}",
            "assumptions": ["Fixture mode contains synthetic data only for the built-in sample questions."],
            "constraints": [],
            "ambiguity_note": None,
            "freshness_days": None,
            "target_entity_count": None,
            "candidate_entities": [],
            "criteria": [
                {
                    "id": "K1",
                    "description": "Direct evidence answering the question",
                    "kind": "general",
                    "required": True,
                    "needs_freshness": False,
                    "comparative": False,
                    "key_terms": tokenize(question)[:6],
                }
            ],
            "queries": [{"text": question[:200], "purpose": "Direct search", "criterion_ids": ["K1"], "topic": "general"}],
            "steps": ["Search for the question", "Read the most relevant sources", "Summarize what the evidence supports"],
        }

    # -- extract ---------------------------------------------------------

    def _extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = []
        if self.scenario is None:
            return {"evidence": items}
        for passage in payload.get("passages") or []:
            text = normalize_for_match(passage["text"])
            for fact in self.scenario.facts:
                if normalize_for_match(fact["quote"]) in text:
                    items.append(
                        {
                            "passage_id": passage["id"],
                            "quote": fact["quote"],
                            "claim": fact["claim"],
                            "criterion_ids": fact["criteria"],
                            "entity": fact.get("entity"),
                            "polarity": fact.get("polarity", "supports"),
                        }
                    )
        passages = payload.get("passages") or []
        if passages:
            for bad in self.scenario.bad_extractions:
                items.append(
                    {
                        "passage_id": bad.get("passage_id") or passages[0]["id"],
                        "quote": bad["quote"],
                        "claim": bad["claim"],
                        "criterion_ids": bad.get("criteria", ["K1"]),
                        "entity": bad.get("entity"),
                        "polarity": "supports",
                    }
                )
        return {"evidence": items}

    # -- follow-up -------------------------------------------------------

    def _follow_up(self, payload: dict[str, Any]) -> dict[str, Any]:
        gaps = {g["criterion_id"] for g in payload.get("gaps") or []}
        previous = {" ".join(q.casefold().split()) for q in payload.get("previous_queries") or []}
        actions = []
        for step in self.scenario.follow_up if self.scenario else []:
            text = self.scenario.queries[step["query"]] if self.scenario else ""
            if gaps & set(step["criteria"]) and " ".join(text.casefold().split()) not in previous:
                actions.append(
                    {
                        "tool": "search_web",
                        "query": text,
                        "topic": "general",
                        "source_ids": [],
                        "criterion_ids": [c for c in step["criteria"] if c in gaps],
                        "reason": step.get("reason", "close a coverage gap"),
                    }
                )
        if not actions:
            return {"actions": [], "stop": True, "stop_reason": "No further searches are likely to close the remaining gaps."}
        return {"actions": actions, "stop": False, "stop_reason": None}

    # -- synthesize ------------------------------------------------------

    def _evidence_for(self, rows: list[dict[str, Any]], fact_keys: list[str], *, require_all: bool = False) -> list[str]:
        """Evidence ids for scripted fact keys. With require_all, [] unless every fact was found in this run."""
        assert self.scenario is not None
        quotes = {f["key"]: normalize_for_match(f["quote"]) for f in self.scenario.facts if f.get("key") in fact_keys}
        found = {key: r["id"] for key, q in quotes.items() for r in rows if normalize_for_match(r["quote"]) == q}
        if require_all and len(found) < len(fact_keys):
            return []
        return list(dict.fromkeys(found.values()))

    def _synthesize(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = payload.get("evidence") or []
        plan = payload.get("plan") or {}
        criteria = plan.get("criteria") or []
        syn = self.scenario.synthesis if self.scenario else {}
        supporting = [r for r in rows if r["polarity"] == "supports"]

        findings = []
        used: set[str] = set()
        per_criterion = 2 if len(criteria) <= 3 else 1
        for crit in criteria:
            ev = [r for r in supporting if crit["id"] in r["criterion_ids"] and r["id"] not in used]
            ev.sort(key=lambda r: (r["first_party"], r["tier"] != "high"))
            for r in ev[:per_criterion]:
                used.add(r["id"])
                findings.append({"text": r["claim"], "kind": "fact", "criterion_ids": [crit["id"]], "evidence_ids": [r["id"]]})
        for extra in syn.get("findings", []):
            ids = self._evidence_for(rows, extra["facts"])
            if ids:
                findings.append(
                    {
                        "text": extra["text"],
                        "kind": extra.get("kind", "interpretation"),
                        "criterion_ids": extra.get("criteria", []),
                        "evidence_ids": ids,
                    }
                )
        if "overclaim" in syn:
            ids = self._evidence_for(rows, syn["overclaim"]["facts"])
            if ids:
                findings.append(
                    {
                        "text": syn["overclaim"]["text"],
                        "kind": "fact",
                        "criterion_ids": syn["overclaim"].get("criteria", []),
                        "evidence_ids": ids,
                    }
                )
        findings = findings[:8]

        sa = syn.get("short_answer")
        sa_ids = self._evidence_for(rows, sa["facts"], require_all=True) if sa else []
        if sa and sa_ids:
            short = {"text": sa["text"], "evidence_ids": sa_ids}
        elif findings:
            short = {
                "text": " ".join(f["text"] for f in findings[:2]),
                "evidence_ids": [i for f in findings[:2] for i in f["evidence_ids"]],
            }
        else:
            short = {"text": "The reviewed sources did not contain evidence that answers the question.", "evidence_ids": []}

        comparison = None
        if plan.get("task_type") == "comparison":
            dims = [c["id"] for c in criteria if c["kind"] == "dimension"]
            rows_out = []
            entities_found = [r["entity"] for r in supporting if r.get("entity")]
            ranked = sorted(dict.fromkeys(entities_found), key=lambda e: -entities_found.count(e))
            limit = plan.get("target_entity_count") or 4
            for entity in plan.get("candidate_entities") or ranked[:limit]:
                cells = []
                for cid in dims:
                    ev = [r for r in supporting if cid in r["criterion_ids"] and r["entity"] == entity]
                    if ev:
                        cells.append(
                            {
                                "criterion_id": cid,
                                "text": ev[0]["claim"],
                                "evidence_ids": [e["id"] for e in ev[:2]],
                                "unknown": False,
                            }
                        )
                    else:
                        cells.append(
                            {"criterion_id": cid, "text": "Not found in reviewed sources", "evidence_ids": [], "unknown": True}
                        )
                rows_out.append({"entity": entity, "cells": cells})
            comparison = {"criteria": dims, "rows": rows_out} if dims else None

        entities = []
        if plan.get("task_type") == "entity_discovery":
            eligibility = [c["id"] for c in criteria if c["kind"] == "eligibility"]
            names = list(dict.fromkeys(r["entity"] for r in rows if r.get("entity")))
            for name in names:
                ent_rows = [r for r in rows if r.get("entity") == name]
                checks = []
                for cid in eligibility:
                    pro = [r for r in ent_rows if cid in r["criterion_ids"] and r["polarity"] == "supports"]
                    con = [r for r in ent_rows if cid in r["criterion_ids"] and r["polarity"] == "contradicts"]
                    if con:
                        checks.append(
                            {"criterion_id": cid, "status": "not_met", "text": con[0]["claim"], "evidence_ids": [con[0]["id"]]}
                        )
                    elif pro:
                        checks.append(
                            {"criterion_id": cid, "status": "met", "text": pro[0]["claim"], "evidence_ids": [pro[0]["id"]]}
                        )
                    else:
                        checks.append(
                            {
                                "criterion_id": cid,
                                "status": "unknown",
                                "text": "Not found in reviewed sources",
                                "evidence_ids": [],
                            }
                        )
                other = [r for r in ent_rows if not set(r["criterion_ids"]) & set(eligibility)]
                summary = {"text": other[0]["claim"], "evidence_ids": [other[0]["id"]]} if other else None
                included = all(c["status"] == "met" for c in checks)
                reason = None
                if not included:
                    reason = (
                        "Evidence contradicts an eligibility condition."
                        if any(c["status"] == "not_met" for c in checks)
                        else "Eligibility not confirmed by the reviewed sources."
                    )
                entities.append(
                    {"name": name, "included": included, "summary": summary, "eligibility": checks, "exclusion_reason": reason}
                )

        conflicts = []
        for crit in criteria:
            by_entity: dict[Any, dict[str, list[str]]] = {}
            for r in rows:
                if crit["id"] in r["criterion_ids"]:
                    by_entity.setdefault(r.get("entity"), {}).setdefault(r["polarity"], []).append(r["id"])
            for entity, pol in by_entity.items():
                if pol.get("supports") and pol.get("contradicts"):
                    conflicts.append(
                        {
                            "description": syn.get("conflict_description")
                            or f"Sources disagree on {crit['description'].lower()}.",
                            "criterion_ids": [crit["id"]],
                            "evidence_ids": pol["supports"][:2] + pol["contradicts"][:2],
                            "entity": entity,
                            "resolution": None,
                        }
                    )

        return {
            "short_answer": short,
            "key_findings": findings,
            "comparison": comparison,
            "entities": entities,
            "conflicts": conflicts,
            "limitations": syn.get("limitations", []),
            "next_steps": syn.get("next_steps", []),
        }

    # -- verify ----------------------------------------------------------

    def _verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        evidence = payload.get("evidence") or {}
        verdicts = []
        for claim in payload.get("claims") or []:
            cited = [evidence[e] for e in claim.get("evidence_ids") or [] if e in evidence]
            verdict, issue = judge_support(claim["text"], [f"{c['quote']} {c['passage']}" for c in cited])
            verdicts.append({"claim_id": claim["id"], "verdict": verdict, "issue": issue})
        return {"verdicts": verdicts}

    # -- repair ----------------------------------------------------------

    def _repair(self, payload: dict[str, Any]) -> dict[str, Any]:
        by_id = {e["id"]: e for e in payload.get("evidence") or []}
        repairs = []
        for claim in payload.get("claims") or []:
            cited = [by_id[e] for e in claim.get("evidence_ids") or [] if e in by_id]
            if cited:
                repairs.append(
                    {"claim_id": claim["id"], "action": "rewrite", "text": cited[0]["claim"], "evidence_ids": [cited[0]["id"]]}
                )
            else:
                repairs.append({"claim_id": claim["id"], "action": "remove", "text": "", "evidence_ids": []})
        return {"repairs": repairs}


def judge_support(claim: str, evidence_texts: list[str]) -> tuple[str, str | None]:
    """Lexical support heuristic used by the fixture verifier (and the offline baseline judge)."""
    if not evidence_texts:
        return "not_supported", "No cited evidence."
    joined = " ".join(evidence_texts).casefold()
    lowered = claim.casefold()
    for marker in UNSUPPORTED_MARKERS:
        pattern = r"\b" + re.escape(marker) + r"\b"
        if re.search(pattern, lowered) and not re.search(pattern, joined):
            return "not_supported", f"The claim says '{marker}', which the cited evidence does not state."
    words = set(tokenize(claim))
    if not words:
        return "not_supported", "Claim has no checkable content."
    have = set(tokenize(joined))
    ratio = len(words & have) / len(words)
    if ratio >= SUPPORTED_RATIO:
        return "supported", None
    if ratio >= PARTIAL_RATIO:
        return "partially_supported", "Parts of the claim go beyond the cited evidence."
    return "not_supported", "The cited evidence does not state this."
