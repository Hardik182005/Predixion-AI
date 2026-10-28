# Evaluation results: live mode

- Run at: 2026-10-28T11:40:07+00:00 (UTC)
- Model: gpt-6.1-terra, reasoning effort low, openai SDK 3.40.0
- Prompt version: 2026-10-28.3; git commit: uncommitted
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.2012 of $0.30 limit

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| memory_comparison | assignment_example | completed (criteria_satisfied) | 1/6 | 2/6 | 5/5 / 0/5 | 72.8 / 7.9 | 0.0727 / 0.0370 |
| vector_db_comparison | assignment_example | completed (criteria_satisfied) | 1/6 | 0/0 | 1/4 / 0/4 | 58.8 / 3.1 | 0.0654 / 0.0261 |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 2 | 2 |
| checks_passed | 6 | 3 |
| checks_total | 6 | 4 |
| claims | 12 | 6 |
| supported | 2 | 2 |
| partially_supported | 6 | 1 |
| not_supported | 4 | 3 |
| supported_rate | 0.167 | 0.333 |
| invalid_citations | 0 | 0 |
| criteria_covered | 6 | 0 |
| criteria_total | 9 | 9 |
| reported_criteria_supported | 9 | None |
| latency_s_median | 65.8 | 5.48 |
| latency_s_total | 131.59 | 10.97 |
| cost_usd_total | 0.1381 | 0.0631 |

## Expected vs actual

### memory_comparison

Question: Compare approaches to memory in an AI support agent.

Expected: Compares memory approaches on the planned dimensions with cited findings and a comparison table.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: answers pass, citations_resolve pass, comparison_table pass.
- Baseline: completed. Checks: answers pass, citations_resolve pass, comparison_table n/a.
  - agent claim scored partially_supported: "Conversation context supports current-session reasoning; persistent memory can supply facts across sessions. A dynamic summary combined with a user graph is one demonstrated hybrid design." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored not_supported: "Graphs can represent relationships and changes, at the cost of additional modeling complexity. In one implementation, weights favor newer knowledge when retrieved facts conflict; recency alone should not be assumed to establish correctness." (The cited evidence does not state this.)
  - baseline claim scored partially_supported: "Working memory, semantic memory, episodic memory, and procedural memory serve distinct support-agent needs." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored not_supported: "Short-term memory does not retain information across sessions." (The cited evidence does not state this.)

### vector_db_comparison

Question: Compare the top three open-source vector databases for a startup building RAG products.

Expected: Compares three open-source vector databases; vendor claims stay attributed and unsupported superlatives are dropped.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: answers pass, citations_resolve pass, comparison_table pass.
- Baseline: insufficient_evidence. Checks: answers FAIL, citations_resolve pass, comparison_table n/a.
  - agent claim scored not_supported: "The selection is based on their inclusion in a vector database comparison and their documented RAG-relevant features, not a measured adoption ranking. Adoption figures were not found." (The cited evidence does not state this.)
  - agent claim scored not_supported: "All three are described as open-source vector databases, but the reviewed evidence does not identify their licenses." (The cited evidence does not state this.)
