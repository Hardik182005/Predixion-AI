# Evaluation results: fixture mode

- Run at: 2026-10-28T11:45:20+00:00 (UTC)
- Model: fixture-heuristic-v1
- Prompt version: 2026-10-28.3; git commit: uncommitted
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.0000 of $3.00 limit
- Fixture mode: synthetic pages and scripted models. These numbers check the pipeline, not model quality.

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| memory_comparison | assignment_example | completed (criteria_satisfied) | 5/5 | 6/6 | 3/4 / 2/4 | 0.0 / 0.0 | 0.0000 / 0.0000 |
| vector_db_comparison | assignment_example | completed (criteria_satisfied) | 5/6 | 2/6 | 1/4 / 1/4 | 0.0 / 0.0 | 0.0000 / 0.0000 |
| hr_tech_discovery | assignment_example | completed (criteria_satisfied) | 7/7 | 0/0 | 3/3 / 0/3 | 0.0 / 0.0 | 0.0000 / 0.0000 |
| multi_agent_pros_cons | assignment_example | completed (criteria_satisfied) | 5/5 | 0/0 | 3/4 / 0/4 | 0.0 / 0.0 | 0.0000 / 0.0000 |
| nonexistent_product | nonexistent_entity | insufficient_evidence (diminishing_returns) | 0/0 | 0/0 | 0/2 / 0/2 | 0.0 / 0.0 | 0.0000 / 0.0000 |
| ambiguous_mercury | ambiguous_request | completed (criteria_satisfied) | 6/6 | 6/6 | 3/3 / 3/3 | 0.0 / 0.0 | 0.0000 / 0.0000 |
| contradictory_sqlite | contradictory_evidence | partial (rounds_exhausted) | 6/6 | 2/2 | 3/3 / 1/3 | 0.0 / 0.0 | 0.0000 / 0.0000 |
| search_provider_down | provider_failure | failed (provider_unavailable) | 0/0 | 0/0 | 0/4 / 0/4 | 1.0 / 0.2 | 0.0000 / 0.0000 |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 8 | 8 |
| checks_passed | 20 | 11 |
| checks_total | 20 | 14 |
| claims | 35 | 20 |
| supported | 34 | 16 |
| partially_supported | 1 | 1 |
| not_supported | 0 | 3 |
| supported_rate | 0.971 | 0.8 |
| invalid_citations | 0 | 2 |
| criteria_covered | 16 | 7 |
| criteria_total | 27 | 27 |
| reported_criteria_supported | 20 | None |
| latency_s_median | 0.01 | 0.0 |
| latency_s_total | 1.11 | 0.22 |
| cost_usd_total | 0.0 | 0.0 |

## Expected vs actual

### memory_comparison

Question: Compare approaches to memory in an AI support agent.

Expected: Compares memory approaches on the planned dimensions with cited findings and a comparison table.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: answers pass, citations_resolve pass, comparison_table pass.
- Baseline: completed. Checks: answers pass, citations_resolve pass, comparison_table n/a.

### vector_db_comparison

Question: Compare the top three open-source vector databases for a startup building RAG products.

Expected: Compares three open-source vector databases; vendor claims stay attributed and unsupported superlatives are dropped.

- Agent: completed, stop reason criteria_satisfied, confidence medium. Checks: answers pass, citations_resolve pass, comparison_table pass.
- Baseline: completed. Checks: answers pass, citations_resolve FAIL, comparison_table n/a.
  - agent claim scored partially_supported: "The benchmark compared Qdrant, Milvus, and Weaviate on the same hardware, and none of the vendors funded or reviewed the study." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "The benchmark compared Qdrant, Milvus, and Weaviate on the same hardware, and none of the vendors funded or reviewed the study." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored not_supported: "Weaviate guarantees sub-millisecond latency at any scale." (Quote not found in the cited source.)

### hr_tech_discovery

Question: Find five Indian B2B SaaS startups in HR tech and summarize their positioning.

Expected: Lists at most five companies and includes only those whose eligibility is backed by evidence; never pads the list.

- Agent: completed, stop reason criteria_satisfied, confidence medium. Checks: answers pass, citations_resolve pass, entities_not_padded pass, eligibility_backed pass.
- Baseline: insufficient_evidence. Checks: answers FAIL, citations_resolve pass, entities_not_padded n/a, eligibility_backed n/a.

### multi_agent_pros_cons

Question: Research the pros and cons of a multi-agent architecture for customer support automation.

Expected: Gives cited pros and cons of multi-agent support automation.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: answers pass, citations_resolve pass.
- Baseline: insufficient_evidence. Checks: answers FAIL, citations_resolve pass.

### nonexistent_product

Question: What does QuantumLeap Vector Engine 9 from Hyperion DB cost?

Expected: Says it found no evidence for the product and makes no factual claims about it.

- Agent: insufficient_evidence, stop reason diminishing_returns, confidence low. Checks: abstains pass.
- Baseline: insufficient_evidence. Checks: abstains pass.

### ambiguous_mercury

Question: Is mercury dangerous?

Expected: States which meaning of 'mercury' it researched, then answers with citations.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: ambiguity_noted pass, answers pass, citations_resolve pass.
- Baseline: completed. Checks: ambiguity_noted n/a, answers pass, citations_resolve pass.

### contradictory_sqlite

Question: Is SQLite suitable for production web applications?

Expected: Reports that sources disagree instead of silently picking a side.

- Agent: partial, stop reason rounds_exhausted, confidence medium. Checks: conflict_reported pass, answers pass, citations_resolve pass.
- Baseline: completed. Checks: conflict_reported n/a, answers pass, citations_resolve pass.

### search_provider_down

Question: Compare approaches to memory in an AI support agent.

Expected: With search unavailable (injected), fails closed: a failed report with provider_unavailable and no findings.

- Agent: failed, stop reason provider_unavailable, confidence low. Checks: fails_closed pass.
- Baseline: failed. Error: search: server_error: injected: HTTP 503. Checks: fails_closed pass.
