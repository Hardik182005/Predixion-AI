# Evaluation results: live mode

- Run at: 2026-10-28T16:59:06+00:00 (UTC)
- Model: gpt-6.1-terra, reasoning effort low, openai SDK 3.40.0
- Prompt version: 2026-10-28.3; git commit: 5e37466
- Groq models: openai/gpt-oss-120b, openai/gpt-oss-20b; Groq-first tasks: plan, follow_up; fallback between providers: on
- Baseline: one search, up to max_pages_per_run pages, one model call with quoted citations; same model
- Scoring: lexical support of each claim by its cited quotes (fixtures.judge_support); no LLM judge
- Spend: $0.0559 of $0.15 limit

## Per case

| Case | Category | Agent status | Agent supported / claims | Baseline supported / claims | Criteria covered (agent / baseline) | Latency s (agent / baseline) | Cost $ (agent / baseline) |
|---|---|---|---|---|---|---|---|
| nonexistent_product | nonexistent_entity | insufficient_evidence (diminishing_returns) | 0/0 | - | 0/3 / - | 14.1 / - | 0.0559 / - |

## Summary

| Metric | Agent | Baseline |
|---|---|---|
| runs | 1 | - |
| checks_passed | 1 | - |
| checks_total | 1 | - |
| claims | 0 | - |
| supported | 0 | - |
| partially_supported | 0 | - |
| not_supported | 0 | - |
| supported_rate | None | - |
| invalid_citations | 0 | - |
| criteria_covered | 0 | - |
| criteria_total | 3 | - |
| reported_criteria_supported | 0 | - |
| latency_s_median | 14.09 | - |
| latency_s_total | 14.09 | - |
| cost_usd_total | 0.0559 | - |

## Expected vs actual

### nonexistent_product

Question: What does QuantumLeap Vector Engine 9 from Hyperion DB cost?

Expected: Says it found no evidence for the product and makes no factual claims about it.

- Agent: insufficient_evidence, stop reason diminishing_returns, confidence low. Checks: abstains pass.
