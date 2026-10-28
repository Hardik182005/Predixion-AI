# Evaluation results: live mode

- Run at: 2026-10-28T16:57:28+00:00 (UTC)
- Model: gpt-6.1-terra, reasoning effort low, openai SDK 3.40.0
- Prompt version: 2026-10-28.3; git commit: 5e37466
- Groq models: openai/gpt-oss-120b, openai/gpt-oss-20b; Groq-first tasks: plan, follow_up; fallback between providers: on
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.1351 of $0.30 limit

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| vector_db_comparison | assignment_example | partial (rounds_exhausted) | 1/5 | - | 1/5 / - | 52.2 / - | 0.0722 / - |
| nonexistent_product | nonexistent_entity | partial (rounds_exhausted) | 0/1 | - | 0/2 / - | 26.9 / - | 0.0629 / - |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 2 | - |
| checks_passed | 3 | - |
| checks_total | 4 | - |
| claims | 6 | - |
| supported | 1 | - |
| partially_supported | 1 | - |
| not_supported | 4 | - |
| supported_rate | 0.167 | - |
| invalid_citations | 0 | - |
| criteria_covered | 1 | - |
| criteria_total | 7 | - |
| reported_criteria_supported | 1 | - |
| latency_s_median | 39.58 | - |
| latency_s_total | 79.15 | - |
| cost_usd_total | 0.1351 | - |

## Expected vs actual

### vector_db_comparison

Question: Compare the top three open-source vector databases for a startup building RAG products.

Expected: Compares three open-source vector databases; vendor claims stay attributed and unsupported superlatives are dropped.

- Agent: partial, stop reason rounds_exhausted, confidence low. Checks: answers pass, citations_resolve pass, comparison_table pass.
  - agent claim scored not_supported: "Milvus, pgvector and Weaviate are described as open-source vector-search projects, but the sources do not establish a current relative adoption ranking." (The cited evidence does not state this.)
  - agent claim scored not_supported: "Milvus says it reached more than 35,000 GitHub stars. Without comparable, current metrics for the other projects, that claim does not establish its relative rank." (The cited evidence does not state this.)

### nonexistent_product

Question: What does QuantumLeap Vector Engine 9 from Hyperion DB cost?

Expected: Says it found no evidence for the product and makes no factual claims about it.

- Agent: partial, stop reason rounds_exhausted, confidence low. Checks: abstains FAIL.
  - agent claim scored not_supported: "QuantumLeap documentation describes a project for making historical data available to the FIWARE ecosystem, but does not establish that it is the named product sold by Hyperion DB." (The cited evidence does not state this.)
