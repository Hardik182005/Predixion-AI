# Evaluation results: live mode

- Run at: 2026-10-28T17:42:09+00:00 (UTC)
- Model: gpt-6.1-terra, reasoning effort low, openai SDK 3.40.0
- Prompt version: 2026-10-28.4; git commit: b831e7a
- Groq models: openai/gpt-oss-120b, openai/gpt-oss-20b; Groq-first tasks: plan, follow_up; fallback between providers: on
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.2002 of $0.30 limit

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| hr_tech_discovery | assignment_example | partial (rounds_exhausted) | 1/4 | - | 1/5 / - | 60.8 / - | 0.0933 / - |
| vector_db_comparison | assignment_example | partial (rounds_exhausted) | 0/5 | - | 3/5 / - | 71.7 / - | 0.1068 / - |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 2 | - |
| checks_passed | 7 | - |
| checks_total | 7 | - |
| claims | 9 | - |
| supported | 1 | - |
| partially_supported | 4 | - |
| not_supported | 4 | - |
| supported_rate | 0.111 | - |
| invalid_citations | 0 | - |
| criteria_covered | 4 | - |
| criteria_total | 10 | - |
| reported_criteria_supported | 1 | - |
| latency_s_median | 66.27 | - |
| latency_s_total | 132.53 | - |
| cost_usd_total | 0.2002 | - |

## Expected vs actual

### hr_tech_discovery

Question: Find five Indian B2B SaaS startups in HR tech and summarize their positioning.

Expected: Lists at most five companies and includes only those whose eligibility is backed by evidence; never pads the list.

- Agent: partial, stop reason rounds_exhausted, confidence low. Checks: answers pass, citations_resolve pass, entities_not_padded pass, eligibility_backed pass.
  - agent claim scored partially_supported: "SalaryBook targets Indian SMEs with staff, payroll and expense management; its mobile attendance features include selfie and location marking." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored not_supported: "SalaryBook was founded in 2020 and is listed as private, but its incorporation in India is not established in the reviewed evidence." (The cited evidence does not state this.)

### vector_db_comparison

Question: Compare the top three open-source vector databases for a startup building RAG products.

Expected: Compares three open-source vector databases; vendor claims stay attributed and unsupported superlatives are dropped.

- Agent: partial, stop reason rounds_exhausted, confidence low. Checks: answers pass, citations_resolve pass, comparison_table pass.
  - agent claim scored partially_supported: "Consider Milvus for a distributed, large-scale use case: sources list several index types and a billion-scale use case, although some operational edge cases may require community help or reading source code." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored partially_supported: "Consider Weaviate if built-in embedding and reranking modules are useful. It supports native hybrid search, but self-hosting and tuning at scale can require operational expertise." (Parts of the claim go beyond the cited evidence.)
