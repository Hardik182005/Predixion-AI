# Evaluation results: live mode

- Run at: 2026-10-28T11:35:32+00:00 (UTC)
- Model: gpt-6.1-terra, reasoning effort low, openai SDK 3.40.0
- Prompt version: 2026-10-28.2; git commit: uncommitted
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.7609 of $1.20 limit

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| memory_comparison | assignment_example | completed (criteria_satisfied) | 0/4 | 1/6 | 1/4 / 3/4 | 65.7 / 8.2 | 0.0680 / 0.0369 |
| vector_db_comparison | assignment_example | completed (criteria_satisfied) | 1/5 | 0/0 | 2/4 / 0/4 | 75.2 / 4.4 | 0.0784 / 0.0341 |
| hr_tech_discovery | assignment_example | partial (rounds_exhausted) | 2/4 | 3/5 | 0/3 / 1/3 | 72.1 / 9.7 | 0.0915 / 0.0307 |
| multi_agent_pros_cons | assignment_example | partial (rounds_exhausted) | 2/6 | 2/6 | 3/4 / 0/4 | 77.5 / 10.8 | 0.0956 / 0.0275 |
| nonexistent_product | nonexistent_entity | insufficient_evidence (diminishing_returns) | 0/0 | 0/0 | 0/3 / 0/3 | 24.5 / 4.5 | 0.0700 / 0.0284 |
| ambiguous_mercury | ambiguous_request | completed (criteria_satisfied) | 3/5 | 6/6 | 3/3 / 2/3 | 38.1 / 8.1 | 0.0456 / 0.0358 |
| contradictory_sqlite | contradictory_evidence | partial (rounds_exhausted) | 2/6 | 2/6 | 3/4 / 0/4 | 66.0 / 11.4 | 0.0745 / 0.0385 |
| search_provider_down | provider_failure | failed (provider_unavailable) | 0/0 | 0/0 | 0/5 / 0/5 | 12.9 / 0.5 | 0.0054 / 0.0000 |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 8 | 8 |
| checks_passed | 18 | 13 |
| checks_total | 20 | 14 |
| claims | 30 | 29 |
| supported | 10 | 14 |
| partially_supported | 13 | 10 |
| not_supported | 7 | 5 |
| supported_rate | 0.333 | 0.483 |
| invalid_citations | 0 | 0 |
| criteria_covered | 12 | 6 |
| criteria_total | 30 | 30 |
| reported_criteria_supported | 14 | None |
| latency_s_median | 65.83 | 8.16 |
| latency_s_total | 431.93 | 57.49 |
| cost_usd_total | 0.529 | 0.2319 |

## Expected vs actual

### memory_comparison

Question: Compare approaches to memory in an AI support agent.

Expected: Compares memory approaches on the planned dimensions with cited findings and a comparison table.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: answers pass, citations_resolve pass, comparison_table FAIL.
- Baseline: completed. Checks: answers pass, citations_resolve pass, comparison_table n/a.
  - agent claim scored partially_supported: "Working-only memory needs no external memory store but ends with the session. It fits isolated interactions, not cases requiring continuity across sessions." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored not_supported: "Replaying full history avoids a separate retrieval step, but longer sessions increase prompt token use. Selective fact retrieval reduces the material passed to the model, while introducing a choice about what to extract and retrieve." (The cited evidence does not state this.)
  - baseline claim scored not_supported: "Short-term memory keeps session context but does not persist between sessions." (The cited evidence does not state this.)
  - baseline claim scored not_supported: "Sliding windows and summaries have different limitations." (The cited evidence does not state this.)

### vector_db_comparison

Question: Compare the top three open-source vector databases for a startup building RAG products.

Expected: Compares three open-source vector databases; vendor claims stay attributed and unsupported superlatives are dropped.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: answers pass, citations_resolve pass, comparison_table FAIL.
- Baseline: insufficient_evidence. Checks: answers FAIL, citations_resolve pass, comparison_table n/a.
  - agent claim scored partially_supported: "The selection basis is a qualitative independent shortlist that names Milvus, Qdrant, and Weaviate first and describes them as purpose-built vector databases. It is not a benchmark ranking; independent adoption evidence is limited to a Weaviate GitHub listing showing 16.9k stars." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored not_supported: "Milvus is listed under Apache 2.0 and characterized for distributed billion-scale workloads, but its active maintenance is not established by the supplied evidence. Qdrant and Weaviate are described as open source, but their specific core licenses and active maintenance are not established." (The cited evidence does not state this.)

### hr_tech_discovery

Question: Find five Indian B2B SaaS startups in HR tech and summarize their positioning.

Expected: Lists at most five companies and includes only those whose eligibility is backed by evidence; never pads the list.

- Agent: partial, stop reason rounds_exhausted, confidence low. Checks: answers pass, citations_resolve pass, entities_not_padded pass, eligibility_backed pass.
- Baseline: completed. Checks: answers pass, citations_resolve pass, entities_not_padded n/a, eligibility_backed n/a.
  - agent claim scored partially_supported: "Kaam.com describes a SaaS suite spanning hiring, payroll, compliance, performance and analytics, but the reviewed evidence does not establish its Indian headquarters or founding." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored not_supported: "Trainery One is listed as B2B HR SaaS with a Coimbatore location, but its Indian headquarters or founding is not established in the reviewed evidence." (The cited evidence does not state this.)
  - baseline claim scored partially_supported: "Peoplebox.ai positions itself as an AI-native platform for hiring, managing and developing talent." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "Keka offers HR software covering payroll, performance reviews, hiring and onboarding." (Parts of the claim go beyond the cited evidence.)

### multi_agent_pros_cons

Question: Research the pros and cons of a multi-agent architecture for customer support automation.

Expected: Gives cited pros and cons of multi-agent support automation.

- Agent: partial, stop reason rounds_exhausted, confidence medium. Checks: answers pass, citations_resolve pass.
- Baseline: completed. Checks: answers pass, citations_resolve pass.
  - agent claim scored partially_supported: "An orchestration layer can assign tasks, route data, track state, manage handoffs and approvals, and record execution. Interaction structures include state graphs and hierarchies; support tasks range from FAQs and password resets to nuanced complaints." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored partially_supported: "Specialization and parallel work may justify multiple agents for complex workflows, but narrow FAQ handling can avoid coordination overhead with one agent. The available evidence does not quantify a multi-agent advantage for customer support." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored not_supported: "A supervisor can coordinate distinct steps in a customer support workflow." (The cited evidence does not state this.)
  - baseline claim scored not_supported: "Multiple agents can provide separation across security and compliance boundaries." (The cited evidence does not state this.)

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
  - agent claim scored partially_supported: "Metallic, or elemental, mercury exposure often occurs when a spill or broken product exposes mercury to air. High exposures can cause kidney effects, respiratory failure and death." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored partially_supported: "Animal research found that methylmercury exposure in the womb could be much more dangerous to offspring than exposure after birth through breast milk. This suggests prenatal exposure warrants particular concern, although the cited finding comes from animal research." (Parts of the claim go beyond the cited evidence.)

### contradictory_sqlite

Question: Is SQLite suitable for production web applications?

Expected: Reports that sources disagree instead of silently picking a side.

- Agent: partial, stop reason rounds_exhausted, confidence low. Checks: conflict_reported pass, answers pass, citations_resolve pass.
- Baseline: completed. Checks: conflict_reported n/a, answers pass, citations_resolve pass.
  - agent claim scored not_supported: "SQLite supports transactions and ACID properties. Production planning still needs a backup and recovery approach; a third-party replication tool such as Litestream is one option." (The cited evidence does not state this.)
  - agent claim scored partially_supported: "SQLite says web capacity depends on database usage and that fewer than 100,000 hits per day should generally work, but calls that estimate conservative rather than a hard limit. Treat request counts as a rough signal, not a capacity guarantee." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "SQLite's documentation recommends it for most low- to medium-traffic websites." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored not_supported: "SQLite runs inside the application rather than requiring a separate database server." (The cited evidence does not state this.)

### search_provider_down

Question: Compare approaches to memory in an AI support agent.

Expected: With search unavailable (injected), fails closed: a failed report with provider_unavailable and no findings.

- Agent: failed, stop reason provider_unavailable, confidence low. Checks: fails_closed pass.
- Baseline: failed. Error: search: server_error: injected: HTTP 503. Checks: fails_closed pass.
