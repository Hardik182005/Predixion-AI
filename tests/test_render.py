"""Markdown export treats web and model text as untrusted."""

from __future__ import annotations

import re

import pytest

from predixion.render import esc, render_markdown, safe_url

from .conftest import run_scenario


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[click](javascript:alert(1))", r"\[click\](javascript:alert(1))"),
        ("![pixel](https://evil.example/p.png)", r"\!\[pixel\](https://evil.example/p.png)"),
        ("<script>alert(1)</script>", r"\<script\>alert(1)\</script\>"),
        ("# Fake heading", r"\# Fake heading"),
        ("1. fake list", r"\1. fake list"),
        ("cell | break\nnew line", r"cell \| break new line"),
        ("`code` and *bold*", r"\`code\` and \*bold\*"),
        (None, ""),
    ],
)
def test_escape_neutralizes_markdown(raw: str | None, expected: str) -> None:
    assert esc(raw) == expected


def test_safe_url_allows_only_http() -> None:
    assert safe_url("javascript:alert(1)") == ""
    assert safe_url("data:text/html;base64,PHNjcmlwdD4=") == ""
    assert safe_url("JAVASCRIPT:alert(1)") == ""
    assert safe_url("https://example.com/a b") == "https://example.com/a%20b"
    assert ">" not in safe_url("https://example.com/x><img src=x>")


async def test_rendered_report_contains_no_active_content(settings) -> None:
    report = await run_scenario("agent_memory", settings)
    hostile_source = report.sources[0].model_copy(
        update={"url": "javascript:alert(document.cookie)", "title": "![tracker](https://evil.example/t.png)"}
    )
    hostile_evidence = report.evidence[0].model_copy(
        update={"quote": "<img src=x onerror=alert(1)> [link](https://evil.example)"}
    )
    hostile = report.model_copy(
        update={
            "question": "What is memory?\n# Injected heading",
            "sources": [hostile_source, *report.sources[1:]],
            "evidence": [hostile_evidence, *report.evidence[1:]],
        }
    )
    md = render_markdown(hostile)
    assert "(no link)" in md
    assert "javascript:" not in md
    # Escaped characters render literally; only an unescaped one is active syntax.
    assert not re.search(r"(?<!\\)<img", md)
    assert r"\<img src=x onerror=alert(1)\>" in md
    assert not re.search(r"(?<!\\)!(?<!\\)\[tracker", md)
    assert not re.search(r"(?<!\\)\]\(https://evil", md)
    assert "\n# Injected heading" not in md
    # The newline is collapsed, so the injected "#" lands mid-line where it is plain text.
    assert md.startswith("# What is memory? # Injected heading\n")
    assert "Fixture demo" in md
