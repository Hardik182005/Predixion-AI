# Evaluation results: live mode

- Run at: 2026-10-28T10:04:00+00:00 (UTC)
- Model: gpt-6.1-terra, reasoning effort low, openai SDK 3.40.0
- Prompt version: 2026-10-28.1; git commit: uncommitted
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.8423 of $2.00 limit

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| memory_comparison | assignment_example | partial (rounds_exhausted) | 2/4 | 2/5 | 3/4 / 1/4 | 73.9 / 13.3 | 0.0740 / 0.0372 |
| vector_db_comparison | assignment_example | completed (criteria_satisfied) | 0/4 | 2/6 | 1/5 / 1/5 | 67.5 / 8.6 | 0.0716 / 0.0382 |
| hr_tech_discovery | assignment_example | completed (criteria_satisfied) | 2/5 | 0/0 | 1/3 / 0/3 | 87.0 / 6.5 | 0.0996 / 0.0374 |
| multi_agent_pros_cons | assignment_example | partial (rounds_exhausted) | 3/6 | 2/6 | 4/5 / 0/5 | 74.6 / 13.1 | 0.0956 / 0.0372 |
| nonexistent_product | nonexistent_entity | insufficient_evidence (diminishing_returns) | 0/0 | 0/0 | 0/3 / 0/3 | 26.1 / 5.0 | 0.0775 / 0.0281 |
| ambiguous_mercury | ambiguous_request | partial (rounds_exhausted) | 3/6 | 1/4 | 3/3 / 1/3 | 65.9 / 9.3 | 0.0810 / 0.0271 |
| contradictory_sqlite | contradictory_evidence | partial (rounds_exhausted) | 2/7 | 1/6 | 3/4 / 1/4 | 74.2 / 9.8 | 0.0937 / 0.0388 |
| search_provider_down | provider_failure | failed (provider_unavailable) | 0/0 | 0/0 | 0/4 / 0/4 | 12.2 / 0.9 | 0.0052 / 0.0000 |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 8 | 8 |
| checks_passed | 18 | 13 |
| checks_total | 20 | 14 |
| claims | 32 | 27 |
| supported | 12 | 8 |
| partially_supported | 12 | 13 |
| not_supported | 8 | 6 |
| supported_rate | 0.375 | 0.296 |
| invalid_citations | 0 | 0 |
| criteria_covered | 15 | 4 |
| criteria_total | 31 | 31 |
| reported_criteria_supported | 15 | None |
| latency_s_median | 70.72 | 8.94 |
| latency_s_total | 481.5 | 66.45 |
| cost_usd_total | 0.5982 | 0.2441 |

## Expected vs actual

### memory_comparison

Question: Compare approaches to memory in an AI support agent.

Expected: Compares memory approaches on the planned dimensions with cited findings and a comparison table.

- Agent: partial, stop reason rounds_exhausted, confidence medium. Checks: answers pass, citations_resolve pass, comparison_table FAIL.
- Baseline: completed. Checks: answers pass, citations_resolve pass, comparison_table n/a.
  - agent claim scored partially_supported: "External memory can retain information outside the context window and bring it back when needed. Extraction and retrieval introduce their own failure points: graph ingestion can lose information, and retrieval and reranking affect grounding." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored not_supported: "Evaluate a hybrid of structured fact slots and retrieval alongside simpler baselines on representative support questions, measuring answer quality, latency and cost. A published study compared these strategy families using annotated long-conversation benchmarks and question-level paired statistics." (The cited evidence does not state this.)
  - baseline claim scored partially_supported: "Different memory layers can handle the current ticket, customer facts, past complaints, and refund routines." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "Semantic similarity does not guarantee that retrieved context is relevant." (Parts of the claim go beyond the cited evidence.)

### vector_db_comparison

Question: Compare the top three open-source vector databases for a startup building RAG products.

Expected: Compares three open-source vector databases; vendor claims stay attributed and unsupported superlatives are dropped.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: answers pass, citations_resolve pass, comparison_table FAIL.
- Baseline: completed. Checks: answers pass, citations_resolve pass, comparison_table n/a.
  - agent claim scored not_supported: "An October 2026 comparison reviewed ten databases and suggested Qdrant or Weaviate for dedicated self-hosted retrieval and Milvus for very large collections (E7, E8). An independent RAG guide also identifies distinct use cases for all three (E18). This supports a shortlist, not a numerical adoption…" (The cited evidence does not state this.)
  - agent claim scored partially_supported: "Weaviate supports semantic, keyword, and hybrid search and metadata filtering (E16, E4). The reviewed guide highlights Qdrant for complex filtering and describes its integration ecosystem as growing but smaller than Weaviate's (E18, E20)." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "Qdrant supports structured metadata filtering during similarity search." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored not_supported: "Weaviate combines vector and keyword search and provides configurable modules." (The cited evidence does not state this.)

### hr_tech_discovery

Question: Find five Indian B2B SaaS startups in HR tech and summarize their positioning.

Expected: Lists at most five companies and includes only those whose eligibility is backed by evidence; never pads the list.

- Agent: completed, stop reason criteria_satisfied, confidence high. Checks: answers pass, citations_resolve pass, entities_not_padded pass, eligibility_backed pass.
- Baseline: insufficient_evidence. Checks: answers FAIL, citations_resolve pass, entities_not_padded n/a, eligibility_backed n/a.
  - agent claim scored partially_supported: "Darwinbox is an India-built enterprise HCM provider positioned as an alternative to large enterprise HCM products in Asia." (Parts of the claim go beyond the cited evidence.)
  - agent claim scored partially_supported: "Keka targets firms that skew toward 50–800 employees, with an HR platform spanning hiring through payroll; its stated pitch emphasizes clean user experience and fair pricing." (Parts of the claim go beyond the cited evidence.)

### multi_agent_pros_cons

Question: Research the pros and cons of a multi-agent architecture for customer support automation.

Expected: Gives cited pros and cons of multi-agent support automation.

- Agent: partial, stop reason rounds_exhausted, confidence low. Checks: answers pass, citations_resolve pass.
- Baseline: completed. Checks: answers pass, citations_resolve pass.
  - agent claim scored not_supported: "Specialization, parallel work, and adding domain specialists are potential benefits. They may help with complex support cases, but the reviewed sources do not quantify improvements in customer experience or support scalability (E3, E6, E20)." (The cited evidence does not state this.)
  - agent claim scored partially_supported: "Handoffs and extra interfaces increase coordination, monitoring, and evaluation work. Errors can propagate between agents, while extra model calls and coordination can increase cost and latency (E6, E12, E26, E32)." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "A supervisor can isolate specialist context and invoke subagents in parallel." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "Separate capabilities can have clear team ownership." (Parts of the claim go beyond the cited evidence.)

### nonexistent_product

Question: What does QuantumLeap Vector Engine 9 from Hyperion DB cost?

Expected: Says it found no evidence for the product and makes no factual claims about it.

- Agent: insufficient_evidence, stop reason diminishing_returns, confidence low. Checks: abstains pass.
- Baseline: insufficient_evidence. Checks: abstains pass.

### ambiguous_mercury

Question: Is mercury dangerous?

Expected: States which meaning of 'mercury' it researched, then answers with citations.

- Agent: partial, stop reason rounds_exhausted, confidence medium. Checks: ambiguity_noted pass, answers pass, citations_resolve pass.
- Baseline: completed. Checks: ambiguity_noted n/a, answers pass, citations_resolve pass.
  - agent claim scored partially_supported: "Common exposure routes include eating methylmercury in food and inhaling elemental mercury vapor. Liquid mercury evaporates at room temperature; its vapor has no odor and does not irritate, so it may go unnoticed. Inorganic mercury salts can be corrosive and may damage the kidneys if swallowed. [E1…" (Parts of the claim go beyond the cited evidence.)
  - agent claim scored partially_supported: "Effects can include tremors, coordination problems, impaired vision, learning and memory difficulties, and mood changes. High metallic mercury exposure can cause respiratory failure and death. Exposure before birth and early in life is especially concerning for development. [E3, E8, E16]" (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "Exposure can occur through mercury vapor or contaminated seafood." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "Mercury threatens fetal and early childhood development." (Parts of the claim go beyond the cited evidence.)

### contradictory_sqlite

Question: Is SQLite suitable for production web applications?

Expected: Reports that sources disagree instead of silently picking a side.

- Agent: partial, stop reason rounds_exhausted, confidence low. Checks: conflict_reported pass, answers pass, citations_resolve pass.
- Baseline: completed. Checks: conflict_reported n/a, answers pass, citations_resolve pass.
  - agent claim scored not_supported: "SQLite runs inside the application process without a separate database server, which can simplify deployment. SQLite says it emphasizes reliability and simplicity; the reviewed evidence does not independently quantify its production reliability (E11, E16, E6)." (The cited evidence does not state this.)
  - agent claim scored partially_supported: "For applications with write contention, test WAL mode, an appropriate busy timeout, and transaction behavior under representative load. A five-second busy timeout waits for a held lock before raising an error; BEGIN IMMEDIATE can avoid a class of write-lock upgrade deadlocks (E2, E3, E12, E13)." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored partially_supported: "SQLite is suitable for many low- to medium-traffic websites." (Parts of the claim go beyond the cited evidence.)
  - baseline claim scored not_supported: "SQLite runs inside the application without a separate server process." (The cited evidence does not state this.)

### search_provider_down

Question: Compare approaches to memory in an AI support agent.

Expected: With search unavailable (injected), fails closed: a failed report with provider_unavailable and no findings.

- Agent: failed, stop reason provider_unavailable, confidence low. Checks: fails_closed pass.
- Baseline: failed. Error: search: server_error: injected: HTTP 503. Checks: fails_closed pass.
