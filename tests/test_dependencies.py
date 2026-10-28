"""Source-dependency drill: offline, non-mutating, and honest about what it can say."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from predixion.api import create_app, hash_token
from predixion.cli import main
from predixion.contracts import (
    Claim,
    ClaimKind,
    ClaimLocation,
    Evidence,
    ResearchReport,
    Source,
    SourceState,
    SupportVerdict,
)
from predixion.dependencies import duplicate_family, render_dependencies, source_dependencies

from .conftest import make_settings, run_scenario, scenario

SAMPLE = Path(__file__).parent.parent / "docs" / "samples" / "vector-db-comparison.json"


def _src(i: int, url: str, content_hash: str | None = None, duplicate_of: str | None = None) -> Source:
    return Source(
        id=f"S{i}",
        url=url,
        canonical_url=url,
        domain=url.split("/")[2],
        title="t",
        state=SourceState.read,
        content_hash=content_hash,
        duplicate_of=duplicate_of,
    )


def _ev(i: int, sid: str, crit: str = "K1") -> Evidence:
    return Evidence(id=f"E{i}", source_id=sid, passage_id=f"{sid}.P1", quote="q" * 20, claim="c", criterion_ids=[crit])


def _claim(i: int, ids: list[str], location: ClaimLocation = ClaimLocation.finding) -> Claim:
    return Claim(
        id=f"C{i}", location=location, kind=ClaimKind.fact, text=f"claim {i}", evidence_ids=ids, verdict=SupportVerdict.supported
    )


async def _report(settings) -> ResearchReport:
    return await run_scenario("agent_memory", settings)


def _with(report: ResearchReport, sources, evidence, claims) -> ResearchReport:
    return report.model_copy(update={"sources": sources, "evidence": evidence, "claims": claims})


async def test_single_and_multiple_source_support_and_compound_claims(settings) -> None:
    base = await _report(settings)
    report = _with(
        base,
        [_src(1, "https://a.org/x"), _src(2, "https://b.org/y")],
        [_ev(1, "S1"), _ev(2, "S2", "K2"), _ev(3, "S1", "K2")],
        [_claim(1, ["E1"]), _claim(2, ["E1", "E2"]), _claim(3, ["E2"]), _claim(4, ["E1", "E3"], ClaimLocation.short_answer)],
    )
    analysis = source_dependencies(report, "S1")
    assert analysis.source_ids == ["S1"] and analysis.evidence_removed == ["E1", "E3"]
    assert [d.claim_id for d in analysis.claims_lost] == ["C1", "C4"]  # every citation came from S1
    assert [d.claim_id for d in analysis.claims_weakened] == ["C2"]  # a compound claim keeps E2 only
    assert analysis.claims_weakened[0].remaining_evidence_ids == ["E2"]
    assert analysis.criteria_to_reassess == ["K1", "K2"]
    assert "not a new fact check" in analysis.note
    text = render_dependencies(analysis)
    assert "C1" in text and "keeps E2" in text


async def test_duplicate_source_family_is_removed_together_but_only_when_asked(settings) -> None:
    base = await _report(settings)
    report = _with(
        base,
        [
            _src(1, "https://a.org/x", "h1"),
            _src(2, "https://mirror.net/x", "h1"),
            _src(3, "https://c.org/z", duplicate_of="S1"),
            _src(4, "https://d.org/w"),
        ],
        [_ev(1, "S1"), _ev(2, "S2"), _ev(3, "S4")],
        [_claim(1, ["E1", "E2"]), _claim(2, ["E1", "E3"])],
    )
    assert duplicate_family(report, "S1") == (
        ["S1", "S2", "S3"],
        "the source and its recorded copies (same content hash or duplicate link)",
    )
    family = source_dependencies(report, "S1")
    assert [d.claim_id for d in family.claims_lost] == ["C1"]  # the mirror copy is not independent support
    alone = source_dependencies(report, "S1", include_duplicates=False)
    assert alone.source_ids == ["S1"] and [d.claim_id for d in alone.claims_weakened] == ["C1", "C2"]


async def test_unknown_source_and_non_mutation(settings) -> None:
    report = await _report(settings)
    before = report.model_dump_json()
    with pytest.raises(KeyError):
        source_dependencies(report, "S999")
    source_dependencies(report, report.sources[0].id)
    assert report.model_dump_json() == before


async def test_no_provider_calls_are_made(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    report = await _report(settings)
    import predixion.llm as llm
    import predixion.tools as tools

    def forbidden(*args, **kwargs):
        raise AssertionError("provider call during dependency analysis")

    monkeypatch.setattr(tools.TavilyClient, "_post", forbidden)
    monkeypatch.setattr(llm.OpenAIModel, "generate", forbidden)
    monkeypatch.setattr(llm.GroqModel, "generate", forbidden)
    analysis = source_dependencies(report, report.sources[0].id)
    assert isinstance(analysis.claims_lost, list)


def test_cli_analyzes_a_saved_report_and_rejects_unknown_sources(capsys) -> None:
    assert main(["deps", str(SAMPLE), "--source", "S1"]) == 0
    out = capsys.readouterr().out
    assert "Removed: S1" in out and "not a new fact check" in out
    assert main(["deps", str(SAMPLE), "--source", "S1", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["source_ids"] == ["S1"] and "claims_lost" in data
    assert main(["deps", str(SAMPLE), "--source", "S77"]) == 2
    assert main(["deps", "/nonexistent/report.json", "--source", "S1"]) == 2


def test_api_endpoint_is_owner_scoped() -> None:
    hashes = f"alice:{hash_token('alice-token')},bob:{hash_token('bob-token')}"
    alice, bob = {"Authorization": "Bearer alice-token"}, {"Authorization": "Bearer bob-token"}
    question = scenario("agent_memory").question
    with TestClient(create_app(make_settings(AUTH_MODE="token", API_TOKEN_HASHES=hashes))) as client:
        run_id = client.post("/api/runs", json={"question": question}, headers=alice).json()["run_id"]
        with client.stream("GET", f"/api/runs/{run_id}/events", headers=alice) as response:
            response.read()
        ok = client.get(f"/api/runs/{run_id}/dependencies", params={"source": "S1"}, headers=alice)
        assert ok.status_code == 200 and ok.json()["source_ids"] == ["S1"] and "note" in ok.json()
        assert client.get(f"/api/runs/{run_id}/dependencies", params={"source": "S1"}, headers=bob).status_code == 404
        assert client.get(f"/api/runs/{run_id}/dependencies", params={"source": "S99"}, headers=alice).status_code == 404
        assert client.get(f"/api/runs/{run_id}/dependencies", headers=alice).status_code == 422
