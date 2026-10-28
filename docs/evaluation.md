# Evaluation

This page covers how Predixion AI was evaluated, what the results show, and what they cannot show. Raw results are in [`evals/results/`](../evals/results/), and every number here comes from those files.

**Read this first.** The suite has 8 cases. The prompts were developed against these same cases, every live number comes from a single run, and claims are scored by a lexical heuristic. No human reviewed the results. Treat the numbers as evidence that the system behaves as designed on these cases, not as a benchmark.

## Summary

- **Behavior checks.**
  - Offline fixture suite: the agent passed all 20 checks.
  - Live with `gpt-6.1-terra` on the current prompt: it passed all 16 checks on the 6 cases run.
  - The cheaper `gpt-6-luna` missed one: it did not report the source conflict in the SQLite case.
- **Against a one-pass baseline** (live, terra, full suite, prompt `.2`), the agent:
  - covered about twice as many required criteria (12/30 vs 6/30),
  - was about 8× slower (median 65.8 s vs 8.2 s),
  - cost about 2.3× more ($0.53 vs $0.23 for 8 runs).
- **Lexical claim support** did not favor the agent in that run: 33% of agent claims vs 48% of baseline claims. Spot checks suggest this mostly reflects the scorer, not ungrounded claims; see [Scoring](#scoring) and [Spot check](#spot-check-of-live-claims).
- **Model choice.** On the same 6 cases and prompt, `gpt-6-luna` cost 31% less per suite. It finished with all criteria satisfied in 2 of 6 runs; terra did in 4 of 6. `gpt-6.1-terra` stays the default.

## The suite

The cases are in `src/predixion/evals.py`. Fixture mode runs them against synthetic pages and scripted models. Live mode runs them against OpenAI and Tavily.

| Case | Category | Question | Behavior checks |
|---|---|---|---|
| `memory_comparison` | assignment example | Compare approaches to memory in an AI support agent. | answers, citations_resolve, comparison_table |
| `vector_db_comparison` | assignment example | Compare the top three open-source vector databases for a startup building RAG products. | answers, citations_resolve, comparison_table |
| `hr_tech_discovery` | assignment example | Find five Indian B2B SaaS startups in HR tech and summarize their positioning. | answers, citations_resolve, entities_not_padded, eligibility_backed |
| `multi_agent_pros_cons` | assignment example | Research the pros and cons of a multi-agent architecture for customer support automation. | answers, citations_resolve |
| `nonexistent_product` | nonexistent entity | What does QuantumLeap Vector Engine 9 from Hyperion DB cost? | abstains |
| `ambiguous_mercury` | ambiguous request | Is mercury dangerous? | ambiguity_noted, answers, citations_resolve |
| `contradictory_sqlite` | contradictory evidence | Is SQLite suitable for production web applications? | conflict_reported, answers, citations_resolve |
| `search_provider_down` | provider failure | The memory question, with search failing (injected HTTP 503) | fails_closed |

The checks are deterministic tests on the report structure (`_agent_checks` in `evals.py`):
- **answers**: the run completed or ended partial, with at least one finding.
- **citations_resolve**: every cited evidence ID exists in the report.
- **comparison_table**: there is a comparison with at least two rows.
- **entities_not_padded**: no more included entities than were asked for.
- **eligibility_backed**: every included entity has every eligibility condition met, with cited evidence.
- **abstains**: the status is insufficient evidence, or there are no findings.
- **ambiguity_noted**: the plan records which meaning it chose.
- **conflict_reported**: the report lists a conflict, or marks a criterion as conflicting.
- **fails_closed**: the run failed with a provider error and has no findings.

**Baseline.** The same model, without the agent loop: one search, up to the same page limit, and one model call that must cite quotes. It shows what the extra rounds, extraction, and verification add.

## Scoring

**Claim support** uses `fixtures.judge_support`, a lexical heuristic:
- A claim is **supported** when at least 60% of its content words appear in its cited quotes.
- It is **partially supported** at 40% or more.
- Otherwise it is **not supported**.
- A claim that uses a superlative or absolute word ("best", "fastest", "always", "guaranteed", and so on) that the quotes do not use is not supported.

There is no LLM judge, on purpose. An LLM judge cannot certify that a claim is correct, and it would share blind spots with the model being tested. The lexical score is deterministic and cheap, but it is a conservative lower bound with two known biases:
- **Paraphrase scores low.** A faithful restatement in different words scores as partial or not supported.
- **Claims about missing evidence score low.** The agent is told to say plainly when evidence is missing, for example "the reviewed evidence does not identify their licenses". By construction, the quotes do not contain those words.

**Criteria covered.** A required criterion counts as covered when a supported or partially supported claim shares at least two of its key terms. The tables also show the agent's own coverage table, labeled "self-reported", for comparison.

**Fixture numbers are circular.** In fixture mode, the scripted verifier uses the same `judge_support` function as the scorer. The fixture claim-support rate (34/35) shows that the pipeline is wired correctly, not that the answers are good.

## Confidence rubric

The confidence shown on each report comes from code (`grounding.assess_confidence`), not from the model. There are no probabilities. It uses these rules, in order:

1. **Low** if the run failed, found insufficient evidence, was cancelled or interrupted, or claim verification did not run.
2. **High** if all of these hold:
   - the run completed,
   - every required criterion is supported,
   - at least 90% of checked claims are fully supported,
   - evidence comes from at least 3 independent sites (registrable domains),
   - there are no unresolved conflicts,
   - no required criterion rests only on old or undated sources,
   - at most half of the evidence is first-party (vendor or company) material.
3. **Medium** if at least 60% of required criteria are supported, at least 75% of checked claims are supported, and evidence comes from at least 2 sites.
4. **Low** otherwise.

The report lists the reasons, such as "4 of 4 required criteria are supported; 19 of 19 checked claims are fully supported; evidence comes from 5 independent sites", and stores the raw factors. The number of high-suitability sources is recorded but not used. The spot check below shows why that matters.

## Results

### Fixture suite (offline, no provider calls)

From [`fixture.md`](../evals/results/fixture.md), prompt `2026-10-28.3`:

| | Agent | Baseline |
|---|---|---|
| Checks passed | 20/20 | 11/14 |
| Claims supported (circular, see above) | 34/35 | 16/20 |
| Invalid citations | 0 | 2 |
| Required criteria covered | 16/27 | 7/27 |

These runs serve as the regression suite. They run offline in about a second and cost nothing.

### Live: agent vs one-pass baseline

From [`live-gpt-6.1-terra.md`](../evals/results/live-gpt-6.1-terra.md): `gpt-6.1-terra`, reasoning effort low, prompt `2026-10-28.2`, all 8 cases, run 2026-10-28 11:35 UTC.

| | Agent | Baseline |
|---|---|---|
| Checks passed | 18/20 | 13/14 |
| Claims supported (lexical) | 10/30 (33%) | 14/29 (48%) |
| Invalid citations | 0 | 0 |
| Required criteria covered (lexical) | 12/30 | 6/30 |
| Median latency | 65.8 s | 8.2 s |
| Estimated cost, 8 runs | $0.529 | $0.232 |

**How to read this:**
- The agent's two failed checks were `comparison_table` on the two comparison questions. Prompt `.3` fixed this; see the next section.
- On the other checks, the agent stopped where it should:
  - It abstained on the nonexistent product.
  - It noted the ambiguity in "mercury".
  - It reported the SQLite conflict.
  - It failed closed when search was down.
- The baseline also abstained correctly on the nonexistent product. In the `gpt-6-luna` run it produced 2 invalid citations and failed `citations_resolve` once; the agent produced none in any run.
- The lower lexical support rate for the agent comes with longer, more qualified claims. Many state what the evidence does not show, which the scorer marks unsupported. This run alone cannot say whether the agent's claims are better or worse grounded than the baseline's. The spot check below is the only direct look.

### Prompt changes during development

The live results were used to find bugs and change the prompts. This is the main overfitting risk: no held-out cases exist, so a check that passes after a fix shows the fix works on that case, not that it generalizes.

| Prompt | What changed | Live result, terra |
|---|---|---|
| `2026-10-28.1` | Initial version. | Agent 18/20 checks (`comparison_table` failed on memory and vector), 12/32 claims supported, 15/31 criteria, median 70.7 s, $0.598. Baseline 13/14 checks, 8/27, 4/31, $0.244. [history](../evals/results/history/) |
| `2026-10-28.2` | Inline citation markers in the answer, and fixes to how discovered entities appear in the table. | Agent 18/20 (`comparison_table` still failed ×2), 10/30 supported, 12/30 criteria, median 65.8 s, $0.529. |
| `2026-10-28.3` | The planner classifies "compare approaches to X" and "top N" questions as comparisons and requires dimension criteria. Synthesis builds a comparison table whenever options are compared, named or discovered. Eligibility criteria come only from conditions the question states. | All checks pass on the 6 cases run: [recheck](../evals/results/live-gpt-6.1-terra-comparison-recheck.md) plus the [remaining four](../evals/results/live-gpt-6.1-terra-prompt3-rest.md). `contradictory_sqlite` and `search_provider_down` have not been re-run on `.3` with terra. |

### Model choice: `gpt-6.1-terra` vs `gpt-6-luna`

Both models ran agent-only on prompt `2026-10-28.3`, on the same 6 cases. Each case ran once, minutes apart, against the live web.

Sources:
- terra: [recheck](../evals/results/live-gpt-6.1-terra-comparison-recheck.md) and [rest](../evals/results/live-gpt-6.1-terra-prompt3-rest.md).
- luna: [first six](../evals/results/live-gpt-6-luna.md) and [last two](../evals/results/live-gpt-6-luna-rest.md).

| Case | terra: status, confidence | luna: status, confidence | Self-reported criteria (terra / luna) | Latency s (terra / luna) | Cost $ (terra / luna) |
|---|---|---|---|---|---|
| memory_comparison | completed, high | partial, medium | 5/5 / 3/4 | 72.8 / 86.3 | 0.073 / 0.046 |
| vector_db_comparison | completed, high | partial, medium | 4/4 / 3/4 | 58.8 / 81.8 | 0.065 / 0.062 |
| hr_tech_discovery | partial, medium | partial, low | 2/3 / 0/4 | 87.1 / 67.5 | 0.089 / 0.061 |
| multi_agent_pros_cons | completed, high | completed, medium | 4/4 / 4/4 | 65.1 / 55.2 | 0.073 / 0.036 |
| nonexistent_product | insufficient evidence, low | insufficient evidence, low | 0/2 / 0/2 | 24.8 / 24.1 | 0.077 / 0.057 |
| ambiguous_mercury | completed, high | completed, medium | 3/3 / 3/3 | 43.6 / 46.8 | 0.052 / 0.036 |

Each model wrote its own plan, so the criteria differ between the two columns.

| Totals on the 6 shared cases | terra | luna |
|---|---|---|
| Checks passed | 16/16 | 16/16 |
| Completed with all required criteria supported | 4 | 2 |
| Claims supported (lexical) | 12/28 | 13/30 |
| Required criteria covered (lexical) | 12/21 | 14/21 |
| Required criteria supported (self-reported) | 18/21 | 13/21 |
| Median latency | 61.9 s | 61.4 s |
| Estimated cost | $0.429 | $0.297 |
| Of which model tokens | $0.205 | $0.025 |

On the remaining two cases, luna:
- **`contradictory_sqlite`:** completed with high confidence and **failed `conflict_reported`**. It answered without flagging the disagreement between sources. terra on prompt `.2` reported the conflict and ended partial with low confidence.
- **`search_provider_down`:** failed closed, as expected.

**What this shows:**
- **Cost.** Luna's token cost is about a tenth of terra's. Search and extraction (Tavily credits at $0.008 each) then dominate, so the suite total falls only 31%. Luna also used more rounds and pages: it ended partial more often, which raised its search cost.
- **Lexical scores** are about the same for the two models.
- **Outcomes.** terra more often reached the stop condition with every required criterion supported. Luna never reported high confidence on the six shared cases. The one time it did, on SQLite, it had missed the conflict, which is the failure this product exists to prevent.
- **Confounds.** One run each, live web results that change between runs, and different plans per model.

**Decision.** `gpt-6.1-terra` at reasoning effort low stays the default. `gpt-6-luna` is a reasonable choice when cost matters more than completeness. To switch, set:
- `RESEARCH_MODEL=gpt-6-luna`
- `MODEL_INPUT_USD_PER_MTOK=0.10` and `MODEL_OUTPUT_USD_PER_MTOK=0.50`, so cost caps use luna's prices

For evaluation runs, use `--model gpt-6-luna --input-usd-per-mtok 0.10 --output-usd-per-mtok 0.50`.

**Prices** (USD per million tokens, input / output):
- `gpt-6.1-terra`: $1 / $5, from the list price in `config.py`, checked 2026-10-28.
- `gpt-6-luna`: $0.10 / $0.50, cross-checked on 2026-10-28 against third-party price trackers. These are not OpenAI's own page; re-verify before relying on them.
  - [anotherwrapper.com](https://anotherwrapper.com/tools/llm-pricing/gpt-6-luna)
  - [eesel.ai](https://www.eesel.ai/blog/gpt-6-luna-pricing)
  - [llmgateway.io](https://llmgateway.io/models/gpt-6-luna)
  - [pricepertoken.com](https://pricepertoken.com/pricing-page/model/openai-gpt-6-luna)
  - [developersdigest.tech](https://www.developersdigest.tech/models/gpt-6-luna)

### Spot check of live claims

The development assistant (an AI, not the owner) compared four findings from the live vector-database report against their cited quotes. That report is [sample](samples/vector-db-comparison.md), prompt `.3`. The code already guarantees that every quote appears in the page text it was taken from.

| Finding (shortened) | Cited quote (shortened) | Lexical score | Assessment |
|---|---|---|---|
| All three are described as open source; the evidence does not identify their licenses. | E3 "Type \| Open-source, Rust-based…", E7 "Weaviate is an open-source vector database…", E13 "Milvus (an open-source vector database)" | not supported | Grounded. The quotes call each one open source and none names a license. |
| All three support hybrid search and metadata filtering; LangChain and LlamaIndex integrations are named for Weaviate only. | E12 "Milvus, Weaviate, Qdrant, and others support hybrid search…", E11 "All databases support metadata filtering…", E4 "Weaviate \| … \| LangChain, LlamaIndex" | partial | Grounded. |
| Qdrant handles frequent updates well; Milvus needs an index rebuild after large bulk updates. | E10 "Pinecone and Qdrant handle frequent updates well. Milvus requires index rebuild for optimal performance after large bulk updates." | partial | Grounded, almost verbatim. |
| Milvus suits larger scale but needs engineering resources; Weaviate and Qdrant have managed and self-hosted options. | E1 "billions of vectors at lower cost; requires engineering resources", E3 and E4 on managed and self-hosted options | partial | Grounded. |

The run's own verifier marked 19 of 19 checked claims supported. The lexical scorer marked 1 of the report's 6 findings supported. This gap is why the lexical rate is called a lower bound. Four claims are too few to estimate an accuracy rate.

**Problems seen while reading the sample reports:**
- **Overstated confidence on the vector report.**
  - The criterion "verify an open-source core and identify its license" is marked supported, although no license was found. Coverage is assessed per criterion, so a two-part criterion can pass when only one part is established.
  - Confidence is High although none of the sources behind its evidence is rated high-suitability. They are third-party articles and vendor blogs from five sites. The rubric does not require high-suitability sources.
  - Both are worth tightening.
- **The HR discovery report confirms 1 of the 5 companies asked for.** It excludes the other candidates because the pages it read did not state their Indian origin or startup status. Leaving them out rather than padding is the intended behavior, but the answer falls far short of what was asked.
- **Generic conflict entries.** The SQLite report on prompt `.2` lists two conflicts as "Sources disagree on K2 about SQLite. Unresolved." without saying what the disagreement is.
- **Wide comparison tables.** The Markdown export uses the full criterion text as each column header.

## Measured performance

From all live agent runs on 2026-10-28 (both models, all prompt versions):

| | Value |
|---|---|
| Agent latency | 24–87 s for runs that researched; about 12 s when search was down |
| Baseline latency | 3–13 s |
| Agent cost per run | $0.03–$0.10 (terra $0.05–$0.10, luna $0.03–$0.06); under $0.01 when search was down |
| Where agent time goes (terra, prompt `.3`) | model calls about 90%: extract 31%, synthesize 29%, plan 17%, verify 7%, follow-up and repair 6%. Search 8%, page reads 3%. |
| Live spend for all evaluation runs | $2.56 estimated, in the result files, within the $3 limit set for development |

Costs are estimates from list prices and Tavily credits, computed by the app. They are not invoices.

## Reproducing

```bash
uv run predixion eval --mode fixture                      # offline, free; writes evals/results/fixture.{json,md}

# Live: needs OPENAI_API_KEY and TAVILY_API_KEY. --max-spend caps the estimated suite cost.
uv run predixion eval --mode live --max-spend 1.20 --out evals/results/live-gpt-6.1-terra.json
uv run predixion eval --mode live --no-baseline --scenario vector_db_comparison --max-spend 0.30 \
    --save-reports evals/results/scratch/reports --out evals/results/scratch/vector.json
uv run predixion eval --mode live --model gpt-6-luna --input-usd-per-mtok 0.10 --output-usd-per-mtok 0.50 \
    --max-spend 0.45 --out evals/results/scratch/luna.json
```

Live runs will not reproduce these numbers exactly, because search results and model outputs change.

## Limits of this evaluation

- **Small.** 8 cases, 4 of them from the assignment. One live run per configuration.
- **Not held out.** The prompts were changed after looking at these cases.
- **Lexical scoring only.** No human review and no LLM judge. Verification inside the app checks claims against quotes, not quotes against the world.
- **Partly stale.** Two cases have not been run with terra on the current prompt.
- **No load testing.** There is no measurement of concurrent runs beyond the unit tests of the concurrency limits.
