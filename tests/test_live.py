"""Live smoke test against the real providers. Skipped unless PREDIXION_LIVE_TESTS=1.

Costs roughly one research run (a few cents). Requires OPENAI_API_KEY and
TAVILY_API_KEY in the environment or .env.
"""

from __future__ import annotations

import pytest

from predixion.cli import run_once
from predixion.config import Settings
from predixion.contracts import Mode, ResearchRequest, RunStatus

pytestmark = pytest.mark.live


async def test_live_run_produces_grounded_report() -> None:
    settings = Settings(MAX_ROUNDS=1, MAX_COST_USD_PER_RUN=0.20)  # type: ignore[call-arg]
    if not settings.live_available:
        pytest.skip("live credentials are not configured")
    request = ResearchRequest(
        question="What is retrieval-augmented generation and what are its main failure modes?", max_rounds=1
    )
    report = await run_once(settings, request, Mode.live, quiet=True)

    assert report.mode == Mode.live
    assert report.status in (RunStatus.completed, RunStatus.partial, RunStatus.insufficient_evidence)
    assert report.execution.metrics.estimated_cost_usd <= 0.20
    evidence = {e.id: e for e in report.evidence}
    for finding in report.key_findings:
        assert set(finding.evidence_ids) <= set(evidence)
