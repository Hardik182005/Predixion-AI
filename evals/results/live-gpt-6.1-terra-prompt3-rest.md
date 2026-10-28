# Evaluation results: live mode

- Run at: 2026-10-28T11:56:36+00:00 (UTC)
- Model: gpt-6.1-terra, reasoning effort low, openai SDK 3.40.0
- Prompt version: 2026-10-28.3; git commit: uncommitted
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.2905 of $0.35 limit

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| hr_tech_discovery | assignment_example | partial (rounds_exhausted) | 1/4 | - | 0/3 / - | 87.1 / - | 0.0889 / - |
| multi_agent_pros_cons | assignment_example | completed (criteria_satisfied) | 3/6 | - | 3/4 / - | 65.1 / - | 0.0726 / - |
| nonexistent_product | nonexistent_entity | insufficient_evidence (diminishing_returns) | 0/0 | - | 0/2 / - | 24.8 / - | 0.0772 / - |
| ambiguous_mercury | ambiguous_request | completed (criteria_satisfied) | 6/6 | - | 3/3 / - | 43.6 / - | 0.0518 / - |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 4 | - |
| checks_passed | 10 | - |
| checks_total | 10 | - |
| claims | 16 | - |
| supported | 10 | - |
| partially_supported | 3 | - |
| not_supported | 3 | - |
| supported_rate | 0.625 | - |
| invalid_citations | 0 | - |
| criteria_covered | 6 | - |
| criteria_total | 12 | - |
| reported_criteria_supported | 9 | - |
| latency_s_median | 54.37 | - |
| latency_s_total | 220.65 | - |
| cost_usd_total | 0.2905 | - |

## Expected vs actual

### hr_tech_discovery

Question: Find five Indian B2B SaaS startups in HR tech and summarize their positioning.

Expected: Lists at most five companies and includes only those whose eligibility is backed by evidence; never pads the list.

- Agent: partial, stop reason rounds_exhausted, confidence medium. Checks: answers pass, citations_resolve pass, entities_not_padded pass, eligibility_backed pass.
  - agent claim scored not_supported: "CompUp offers API-driven compensation benchmarking that integrates with HR and payroll systems and updates in real time. The evidence does not specify a narrower target customer segment." (The cited evidence does not state this.)
  - agent claim scored not_supported: "Darwinbox and Eightfold appear on a tracker of SaaS companies described as being out of India, with Indian bases listed. That does not clearly establish that either was founded or is headquartered in India." (The cited evidence does not state this.)

### multi_agent_pros_cons

Question: Research the pros and cons of a multi-agent architecture for customer support automation.

Expected: Gives cited pros and cons of multi-agent support automation.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: answers pass, citations_resolve pass.
  - agent claim scored partially_supported: "Specialization may help with complex, multi-step cases, and independently divisible work may benefit from parallel throughput. Adding a specialist can also make expansion into another domain more manageable. These are potential benefits, not demonstrated support-quality gains in the reviewed eviden…" (Parts of the claim go beyond the cited evidence.)
  - agent claim scored partially_supported: "Disagreements, duplicated work and incomplete handoffs can produce inconsistent responses. Additional model calls and handoffs can also increase latency and cost, while shared state makes failures harder to debug." (Parts of the claim go beyond the cited evidence.)

### nonexistent_product

Question: What does QuantumLeap Vector Engine 9 from Hyperion DB cost?

Expected: Says it found no evidence for the product and makes no factual claims about it.

- Agent: insufficient_evidence, stop reason diminishing_returns, confidence low. Checks: abstains pass.

### ambiguous_mercury

Question: Is mercury dangerous?

Expected: States which meaning of 'mercury' it researched, then answers with citations.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: ambiguity_noted pass, answers pass, citations_resolve pass.
