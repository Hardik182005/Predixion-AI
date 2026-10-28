from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from predixion.contracts import CriterionKind, PlannedQuery, ResearchReport, ResearchRequest, TaskType
from predixion.evals import baseline_spec
from predixion.orchestrator import ResearchRun, normalize_plan
from predixion.prompts import Task, spec

from .conftest import RUN_ID, TODAY, EventLog, fixture_providers, make_settings, run_scenario

QUESTION = "What are the tradeoffs between vector databases for RAG?"


# ---------------------------------------------------------------------------
# Plan normalization


def test_empty_plan_falls_back_to_question() -> None:
    plan = normalize_plan({}, question=QUESTION, max_queries=3)
    assert [c.id for c in plan.criteria] == ["K1"]
    assert plan.criteria[0].description == QUESTION
    assert [q.id for q in plan.queries] == ["Q1"]
    assert plan.queries[0].criterion_ids == ["K1"]
    assert plan.task_type == TaskType.explainer


def test_plan_ids_are_reassigned_and_references_mapped() -> None:
    data: dict[str, Any] = {
        "task_type": "comparison",
        "criteria": [
            {"id": "latency", "description": "Query latency", "kind": "performance", "comparative": True},
            {"id": "cost", "description": "Hosting cost", "kind": "not-a-kind"},
            {"id": "blank", "description": "   "},
        ],
        "queries": [
            {"text": "vector db latency benchmark", "criterion_ids": ["latency"]},
            {"text": "Vector DB latency benchmark", "criterion_ids": ["cost"]},  # case-insensitive duplicate
            {"text": "vector db pricing", "criterion_ids": ["unknown"]},
            {"text": "x"},
            {"text": "vector db managed hosting", "criterion_ids": ["cost"], "topic": "sports"},
            {"text": "one too many", "criterion_ids": ["cost"]},
        ],
        "freshness_days": 1,
        "target_entity_count": 50,
    }
    plan = normalize_plan(data, question=QUESTION, max_queries=3)
    assert [c.id for c in plan.criteria] == ["K1", "K2"]
    assert plan.criteria[1].kind == CriterionKind.general
    assert [q.text for q in plan.queries] == ["vector db latency benchmark", "vector db pricing", "vector db managed hosting"]
    assert [q.criterion_ids for q in plan.queries] == [["K1"], ["K1"], ["K2"]]
    assert plan.queries[2].topic == "general"
    assert plan.freshness_days == 7
    assert plan.target_entity_count == 10


def test_plan_limits_criteria_count() -> None:
    data = {"criteria": [{"description": f"criterion {i}"} for i in range(12)], "queries": [{"text": "q one"}]}
    plan = normalize_plan(data, question=QUESTION, max_queries=3)
    assert len(plan.criteria) == 6


def test_structured_output_schemas_are_strict() -> None:
    """OpenAI strict mode needs every object closed and every property required."""

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for task in Task:
        if task is not Task.baseline:
            walk(spec(task, today=TODAY.isoformat()).schema)
    walk(baseline_spec(make_settings()).schema)


# ---------------------------------------------------------------------------
# Request validation


@pytest.mark.parametrize(
    "fields",
    [
        {"question": "short"},
        {"question": "x" * 1_001},
        {"question": "What is \x1b[31m colored output?"},
        {"question": QUESTION, "max_rounds": 5},
        {
            "question": QUESTION,
            "seed_urls": ["https://a.example/1", "https://a.example/2", "https://a.example/3", "https://a.example/4"],
        },
        {"question": QUESTION, "unexpected": True},
    ],
)
def test_request_rejects_invalid_input(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(**fields)


def test_request_strips_whitespace() -> None:
    assert ResearchRequest(question=f"  {QUESTION}\n").question == QUESTION


# ---------------------------------------------------------------------------
# Follow-up actions: only the two tools, only known sources, no repeats


def _run_with_plan() -> ResearchRun:
    run = ResearchRun(
        RUN_ID, ResearchRequest(question=QUESTION), make_settings(), fixture_providers(None), EventLog(), today=TODAY
    )
    run.plan = normalize_plan(
        {"criteria": [{"description": "latency"}, {"description": "cost"}], "queries": [{"text": "vector database latency"}]},
        question=QUESTION,
        max_queries=3,
    )
    run.queries = [PlannedQuery(id="Q1", text="vector database latency comparison", purpose="", criterion_ids=["K1"])]
    return run


def test_follow_up_actions_are_restricted() -> None:
    run = _run_with_plan()
    actions = [
        {"tool": "shell", "query": "rm -rf /", "source_ids": ["S1"], "criterion_ids": ["K1"]},
        {"tool": "read_sources", "source_ids": ["S2", "S9", "../etc/passwd"], "criterion_ids": ["K2"]},
        {"tool": "search_web", "query": "Vector database latency comparison", "criterion_ids": ["K1"]},
        {"tool": "search_web", "query": "managed vector database pricing", "criterion_ids": ["K9"], "topic": "dark"},
    ]
    queries, reads = run._validate_actions(actions, {"K2"}, {"S2", "S3"}, next_round=2)
    assert reads == ["S2"]
    # The first search is a near-repeat of Q1, and the shell action falls inside the per-round cap.
    assert queries == []

    queries, reads = run._validate_actions(actions[1:], {"K2"}, {"S2", "S3"}, next_round=2)
    assert reads == ["S2"]
    assert [(q.id, q.text, q.criterion_ids, q.topic, q.round) for q in queries] == [
        ("Q2", "managed vector database pricing", ["K2"], "general", 2)
    ]


def test_follow_up_respects_query_cap() -> None:
    run = _run_with_plan()
    actions = [{"tool": "search_web", "query": f"distinct topic number {word}"} for word in ("alpha", "beta", "gamma", "delta")]
    queries, _ = run._validate_actions(actions, {"K1", "K2"}, set(), next_round=2)
    assert len(queries) == run.settings.max_queries_per_round


# ---------------------------------------------------------------------------
# Report contract


async def test_report_round_trips_through_its_schema(settings) -> None:
    report = await run_scenario("agent_memory", settings)
    again = ResearchReport.model_validate_json(report.model_dump_json())
    assert again == report
    assert report.plan is not None
    assert all(e.id.startswith("E") for e in report.evidence)
    evidence_ids = {e.id for e in report.evidence}
    for finding in report.key_findings:
        assert finding.evidence_ids, finding.text
        assert set(finding.evidence_ids) <= evidence_ids
    source_ids = {s.id for s in report.sources}
    assert {e.source_id for e in report.evidence} <= source_ids
