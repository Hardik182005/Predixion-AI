# Evaluation results: live mode

- Run at: 2026-10-28T11:51:53+00:00 (UTC)
- Model: gpt-6-luna, reasoning effort low, openai SDK 3.40.0
- Prompt version: 2026-10-28.3; git commit: uncommitted
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.4077 of $0.45 limit (stopped early)

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| memory_comparison | assignment_example | partial (rounds_exhausted) | 0/6 | 2/6 | 4/4 / 4/4 | 86.3 / 6.6 | 0.0462 / 0.0173 |
| vector_db_comparison | assignment_example | partial (rounds_exhausted) | 1/6 | 0/0 | 3/4 / 0/4 | 81.8 / 3.3 | 0.0615 / 0.0250 |
| hr_tech_discovery | assignment_example | partial (rounds_exhausted) | 3/6 | 1/5 | 0/4 / 0/4 | 67.5 / 5.7 | 0.0606 / 0.0254 |
| multi_agent_pros_cons | assignment_example | completed (criteria_satisfied) | 3/6 | 0/7 | 4/4 / 1/4 | 55.2 / 6.5 | 0.0362 / 0.0174 |
| nonexistent_product | nonexistent_entity | insufficient_evidence (diminishing_returns) | 0/0 | 0/0 | 0/2 / 0/2 | 24.1 / 3.0 | 0.0573 / 0.0252 |
| ambiguous_mercury | ambiguous_request | completed (criteria_satisfied) | 6/6 | - | 3/3 / - | 46.8 / - | 0.0356 / - |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 6 | 5 |
| checks_passed | 16 | 7 |
| checks_total | 16 | 9 |
| claims | 30 | 18 |
| supported | 13 | 3 |
| partially_supported | 9 | 5 |
| not_supported | 8 | 10 |
| supported_rate | 0.433 | 0.167 |
| invalid_citations | 0 | 2 |
| criteria_covered | 14 | 5 |
| criteria_total | 21 | 18 |
| reported_criteria_supported | 13 | None |
| latency_s_median | 61.37 | 5.7 |
| latency_s_total | 361.73 | 25.0 |
| cost_usd_total | 0.2974 | 0.1103 |

## Expected vs actual

### memory_comparison

Question: Compare approaches to memory in an AI support agent.

Expected: Compares memory approaches on the planned dimensions with cited findings and a comparison table.

- Agent: partial, stop reason rounds_exhausted, confidence medium. Checks: answers pass, citations_resolve pass, comparison_table pass.
- Baseline: completed. Checks: answers pass, citations_resolve pass, comparison_table n/a.
  - agent claim scored not_supported: "A long-context approach serializes the full chronological dialogue into the model input; it can use the conversation directly, but the evidence does not establish its cross-session persistence or comparative costs." (The cited evidence does not state this.)
  - agent claim scored partially_supported: "Persistent memory stores information across sessions and can supply preferences and prior context for continuity. The evidence does not specify one required storage format or a universal retrieval mechanism." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored not_supported: "Short-term memory supports coherent exchanges within a session but does not persist after that session ends." (The cited evidence does not state this.)
  - baseline claim scored partially_supported: "Episodic memory preserves specific past events and their outcomes, which can inform later decisions." (Parts of the claim go beyond the cited evidence.)

### vector_db_comparison

Question: Compare the top three open-source vector databases for a startup building RAG products.

Expected: Compares three open-source vector databases; vendor claims stay attributed and unsupported superlatives are dropped.

- Agent: partial, stop reason rounds_exhausted, confidence medium. Checks: answers pass, citations_resolve pass, comparison_table pass.
- Baseline: insufficient_evidence. Checks: answers FAIL, citations_resolve pass, comparison_table n/a.
  - agent claim scored partially_supported: "Weaviate is described as using the BSD-3-Clause license, with both self-hosted and managed-cloud deployment options." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored not_supported: "Qdrant is described as an open-source vector database, but the reviewed evidence does not identify its current license; its eligibility under the stated open-source requirement is therefore unconfirmed." (The cited evidence does not state this.)

### hr_tech_discovery

Question: Find five Indian B2B SaaS startups in HR tech and summarize their positioning.

Expected: Lists at most five companies and includes only those whose eligibility is backed by evidence; never pads the list.

- Agent: partial, stop reason rounds_exhausted, confidence low. Checks: answers pass, citations_resolve pass, entities_not_padded pass, eligibility_backed pass.
- Baseline: completed. Checks: answers pass, citations_resolve FAIL, entities_not_padded n/a, eligibility_backed n/a.
  - agent claim scored not_supported: "The evidence does not establish that CompUp is currently operating, Indian by headquarters or founding, or specifically a B2B SaaS provider. E2 identifies SalaryBook as active, Bengaluru, SaaS, and B2B." (The cited evidence does not state this.)
  - agent claim scored not_supported: "Xoxoday has evidence of company activity and HR-related products, but the reviewed sources do not establish its Indian origin or headquarters; one source lists it in California, United States." (The cited evidence does not state this.)
  - baseline claim scored not_supported: "Keka positions itself as a single platform for employee experience, spanning payroll, performance reviews, hiring, and onboarding." (Quote not found in the cited source.)
  - baseline claim scored not_supported: "Peoplebox.ai combines AI-enabled recruiting with talent-management workflows such as goals, performance, career growth, and compensation." (The cited evidence does not state this.)

### multi_agent_pros_cons

Question: Research the pros and cons of a multi-agent architecture for customer support automation.

Expected: Gives cited pros and cons of multi-agent support automation.

- Agent: completed, stop reason criteria_satisfied, confidence medium. Checks: answers pass, citations_resolve pass.
- Baseline: completed. Checks: answers pass, citations_resolve pass.
  - agent claim scored partially_supported: "Distinct agents can specialize across subtasks and execute work in parallel; specialist agents may also make adding new domains more manageable and sometimes more cost-efficient over time than retraining one large model." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored not_supported: "The evidence describes multi-agent architectures as potentially useful on complex tasks, but does not provide customer-support-specific comparative outcome data demonstrating better resolution quality." (The cited evidence does not state this.)
  - baseline claim scored not_supported: "Specialized agents can divide common support responsibilities such as identifying intent, retrieving knowledge, taking actions, and escalating to a human." (The cited evidence does not state this.)
  - baseline claim scored not_supported: "Narrow specialization may improve answer reliability compared with a generalist bot." (The cited evidence does not state this.)

### nonexistent_product

Question: What does QuantumLeap Vector Engine 9 from Hyperion DB cost?

Expected: Says it found no evidence for the product and makes no factual claims about it.

- Agent: insufficient_evidence, stop reason diminishing_returns, confidence low. Checks: abstains pass.
- Baseline: insufficient_evidence. Checks: abstains pass.

### ambiguous_mercury

Question: Is mercury dangerous?

Expected: States which meaning of 'mercury' it researched, then answers with citations.

- Agent: completed, stop reason criteria_satisfied, confidence medium. Checks: ambiguity_noted pass, answers pass, citations_resolve pass.
