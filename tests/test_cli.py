"""Command-line interface over the same orchestrator as the API."""

from __future__ import annotations

import hashlib
import json

import pytest

from predixion import cli

from .conftest import make_settings, scenario

QUESTION = scenario("agent_memory").question


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # The developer's .env may select live mode; the CLI tests never read it.
    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())


def test_ask_writes_a_markdown_report(tmp_path) -> None:
    out = tmp_path / "report.md"
    assert cli.main(["ask", QUESTION, "--mode", "fixture", "--quiet", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "Fixture demo" in text
    assert "## Short answer" in text


def test_ask_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["ask", QUESTION, "--quiet", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "completed"
    assert report["mode"] == "fixture"


def test_exit_code_for_insufficient_evidence(tmp_path) -> None:
    question = scenario("nonexistent_entity").question
    assert cli.main(["ask", question, "--quiet", "--out", str(tmp_path / "r.md")]) == 3


def test_invalid_input_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["ask", QUESTION, "--mode", "live"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    assert cli.main(["ask", "short", "--mode", "fixture"]) == 2


def test_samples(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["samples"]) == 0
    assert "agent_memory" in capsys.readouterr().out


def test_token_prints_matching_hash(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["token", "--user", "alice"]) == 0
    token, config_line = capsys.readouterr().out.split()
    assert token.startswith("pdx_")
    assert config_line == f"alice:{hashlib.sha256(token.encode()).hexdigest()}"
    assert cli.main(["token", "--user", "bad user!"]) == 2


def test_serve_refuses_public_bind_without_auth(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2
    assert "Refusing to bind" in capsys.readouterr().err
