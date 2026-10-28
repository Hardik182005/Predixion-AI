# Evaluation results: live mode

- Run at: 2026-10-28T11:57:32+00:00 (UTC)
- Model: gpt-6-luna, reasoning effort low, openai SDK 3.40.0
- Prompt version: 2026-10-28.3; git commit: uncommitted
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.0526 of $0.12 limit

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| contradictory_sqlite | contradictory_evidence | completed (criteria_satisfied) | 2/7 | 1/6 | 3/4 / 0/4 | 35.0 / 5.1 | 0.0345 / 0.0175 |
| search_provider_down | provider_failure | failed (provider_unavailable) | 0/0 | 0/0 | 0/4 / 0/4 | 12.7 / 0.6 | 0.0006 / 0.0000 |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 2 | 2 |
| checks_passed | 3 | 3 |
| checks_total | 4 | 3 |
| claims | 7 | 6 |
| supported | 2 | 1 |
| partially_supported | 2 | 0 |
| not_supported | 3 | 5 |
| supported_rate | 0.286 | 0.167 |
| invalid_citations | 0 | 0 |
| criteria_covered | 3 | 0 |
| criteria_total | 8 | 8 |
| reported_criteria_supported | 4 | None |
| latency_s_median | 23.86 | 2.83 |
| latency_s_total | 47.71 | 5.67 |
| cost_usd_total | 0.0352 | 0.0175 |

## Expected vs actual

### contradictory_sqlite

Question: Is SQLite suitable for production web applications?

Expected: Reports that sources disagree instead of silently picking a side.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: conflict_reported FAIL, answers pass, citations_resolve pass.
- Baseline: completed. Checks: conflict_reported n/a, answers pass, citations_resolve pass.
  - agent claim scored not_supported: "Because SQLite runs as a library within the application process, one source says it avoids database-query network round trips; another says it avoids several operational tasks, including database-server maintenance and connection pooling." (The cited evidence does not state this.)
  - agent claim scored partially_supported: "SQLite has limited concurrent writes, characterized in the evidence as a single-writer model. One source reports 400 write transactions per second with WAL on a specified modest EC2 setup, but that benchmark does not establish performance for other workloads or deployments." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored not_supported: "The SQLite project gives fewer than 100,000 daily hits as a conservative guideline, not a strict limit." (The cited evidence does not state this.)
  - baseline claim scored not_supported: "SQLite allows an application to avoid managing a separate database server, reducing operational complexity." (The cited evidence does not state this.)

### search_provider_down

Question: Compare approaches to memory in an AI support agent.

Expected: With search unavailable (injected), fails closed: a failed report with provider_unavailable and no findings.

- Agent: failed, stop reason provider_unavailable, confidence low. Checks: fails_closed pass.
- Baseline: failed. Error: search: server_error: injected: HTTP 503. Checks: fails_closed pass.
