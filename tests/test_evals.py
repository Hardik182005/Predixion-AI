"""Evaluation harness: fixture regression run, baseline scoring, and the suite spend cap."""

from __future__ import annotations

import json

import pytest

from predixion import cli, evals
from predixion.contracts import Mode, SupportVerdict
from predixion.evals import CASES, FixtureOnePass, run_suite, score_baseline_claims
from predixion.fixtures import FixtureExtract, FixtureModel, FixtureSearch
from predixion.prompts import Task

from .conftest import make_settings, scenario

LIVE_KEYS = {"OPENAI_API_KEY": "sk-test-not-real", "TAVILY_API_KEY": "tvly-test-not-real"}


def test_fixture_suite_passes_every_agent_check(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    out = tmp_path / "fixture.json"
    reports = tmp_path / "reports"
    assert cli.main(["eval", "--mode", "fixture", "--out", str(out), "--save-reports", str(reports)]) == 0

    results = json.loads(out.read_text(encoding="utf-8"))
    assert results["mode"] == "fixture" and results["prompt_version"]
    assert [c["id"] for c in results["cases"]] == [c.id for c in CASES]
    agent = results["summary"]["agent"]
    assert agent["checks_passed"] == agent["checks_total"] > 0
    assert agent["invalid_citations"] == 0
    # The scripted baseline keeps the overclaim and bad extractions the agent's verifier removes.
    assert results["summary"]["baseline"]["not_supported"] > agent["not_supported"]
    by_id = {c["id"]: c for c in results["cases"]}
    assert by_id["nonexistent_product"]["agent"]["abstained"]
    assert by_id["search_provider_down"]["agent"]["stop_reason"] == "provider_unavailable"
    assert sorted(p.stem for p in reports.glob("*.json")) == sorted(c.id for c in CASES)

    md = out.with_suffix(".md").read_text(encoding="utf-8")
    assert "These numbers check the pipeline, not model quality" in md
    assert "## Expected vs actual" in md


def test_baseline_claims_are_scored_against_their_quotes() -> None:
    pages = [{"index": 1, "url": "https://example.com/a", "text": "Qdrant supports payload filtering during vector search."}]
    data = {
        "claims": [
            {
                "text": "Qdrant supports payload filtering during vector search.",
                "source": 1,
                "quote": "supports payload filtering",
            },
            {"text": "Qdrant is the fastest database.", "source": 1, "quote": "Qdrant is the fastest database"},
            {"text": "Wrong source number.", "source": 7, "quote": "supports payload filtering"},
            {"text": "Too short a quote.", "source": 1, "quote": "Qdrant"},
            "not an object",
        ]
    }
    claims, invalid = score_baseline_claims(data, pages)
    assert [c.verdict for c in claims] == [
        SupportVerdict.partially_supported,
        SupportVerdict.not_supported,
        SupportVerdict.not_supported,
        SupportVerdict.not_supported,
    ]
    assert claims[0].sources == ["https://example.com/a"]
    assert invalid == 4
    assert score_baseline_claims({"claims": "nope"}, pages) == ([], 0)


class _FakeTavily:
    """Fixture search and extract behind the live client's constructor."""

    name = "fake-tavily"

    def __init__(self, api_key: str) -> None:
        sc = scenario("agent_memory")
        self.search = FixtureSearch(sc).search
        self.extract = FixtureExtract(sc).extract
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeOpenAI:
    model = "fake-live-model"
    sdk_version = "0.0-test"

    def __init__(self, api_key: str, model: str, effort: str) -> None:
        sc = scenario("agent_memory")
        self._agent, self._baseline = FixtureModel(sc), FixtureOnePass(sc)

    async def generate(self, spec, input_text, payload, *, timeout):
        target = self._baseline if spec.task == Task.baseline else self._agent
        return await target.generate(spec, input_text, payload, timeout=timeout)

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("predixion.tools.TavilyClient", _FakeTavily)
    monkeypatch.setattr("predixion.llm.OpenAIModel", _FakeOpenAI)


@pytest.mark.usefixtures("fake_live")
async def test_live_suite_stays_under_max_spend() -> None:
    settings = make_settings(**LIVE_KEYS)
    max_spend = 0.08  # one fixture case costs about $0.03 at the default prices, so the third cannot start
    results = await run_suite([CASES[0]] * 3, settings, Mode.live, max_spend=max_spend)

    runs = [c[s] for c in results["cases"] for s in ("agent", "baseline") if s in c]
    assert runs and all(r["cost_usd"] > 0 for r in runs)  # live prices apply
    assert results["spent_usd"] == pytest.approx(sum(r["cost_usd"] for r in runs), abs=1e-3)
    assert results["spent_usd"] <= max_spend
    assert results["stopped_early"] and len(runs) < 6
    assert results["sdk_version"] == "0.0-test"


@pytest.mark.usefixtures("fake_live")
async def test_live_suite_stops_before_a_run_it_cannot_fund() -> None:
    results = await run_suite(list(CASES), make_settings(**LIVE_KEYS), Mode.live, max_spend=evals.MIN_RUN_CAP_USD / 2)
    assert results["stopped_early"] and results["spent_usd"] == 0
    assert "agent" not in results["cases"][0]
    assert results["summary"]["agent"]["runs"] == 0
    assert "not run" in evals.render_results(results)


def test_eval_usage_errors(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    assert cli.main(["eval", "--mode", "live"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    assert cli.main(["eval", "--scenario", "no_such_case"]) == 2

    monkeypatch.setattr(cli, "get_settings", lambda: make_settings(**LIVE_KEYS))
    assert cli.main(["eval", "--mode", "live", "--model", "some-other-model"]) == 2
    assert "--input-usd-per-mtok" in capsys.readouterr().err
