# Requirements traceability

This file maps each requirement to the code that implements it and the evidence that checks it. Sources: the assignment brief and the project build prompt.

Status values:
- **Done**: implemented and covered by the listed tests or results.
- **Partial**: implemented with a stated gap.
- **Deviation**: done differently from the suggestion, with the reason.
- **Not done**: not implemented.

Test paths are relative to the repository root. Unless marked live, every test runs offline against fixtures.

## Required behavior

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| Accept a research question | `contracts.ResearchRequest` (10–2000 characters, ≤3 seed URLs, 1–4 rounds); `POST /api/runs`; `predixion ask` | `tests/test_plan_contracts.py::test_request_rejects_invalid_input`, `tests/test_api.py::test_rejected_requests`, `tests/test_cli.py::test_invalid_input_exits_2` | Done |
| Interpret objective, constraints, assumptions, freshness | Plan stage: `prompts.PLAN_INSTRUCTIONS`; `orchestrator.normalize_plan` validates and bounds the plan (task type, criteria with kinds, assumptions, freshness window) | `tests/test_plan_contracts.py` (plan normalization tests) | Done |
| Visible structured plan | `plan` event over SSE; `frontend/src/components/RunProgress.tsx` shows criteria and queries | `tests/test_api.py::test_run_streams_events_and_returns_report`, Playwright sample flow | Done |
| Select tools based on task and evidence | Follow-up stage: the model proposes actions only from an allowlist (`search_web` with a query, `read_sources` with discovered source IDs). Code dispatches them and enforces caps. | `tests/test_plan_contracts.py::test_follow_up_actions_are_restricted`, `::test_follow_up_respects_query_cap` | Done |
| At least two distinct tools | `tools.ToolRunner.search_web` (Tavily Search), `tools.ToolRunner.read_sources` (Tavily Extract) | `tests/test_providers.py` | Done |
| Filter noisy, duplicate, irrelevant, weak sources | `orchestrator` register/accept steps with `sources.py`. Filters: URL safety, canonical dedupe, non-text extensions, paywall markers, short pages, near-duplicate shingles, relevance, source tiers. | `tests/test_sources_urls.py::test_register_hit_filters_unsafe_non_text_and_irrelevant_results`, `::test_accept_page_rejects_paywalls_short_pages_and_duplicates`, `::test_near_duplicate_shingles` | Done |
| Structured answer with sources | `contracts.ResearchReport`; `render.py` (Markdown); `frontend/src/components/Report.tsx` | `tests/test_plan_contracts.py::test_report_round_trips_through_its_schema`, `tests/test_render.py`, Vitest `Report` tests | Done |
| Handle failures and incomplete evidence honestly | Statuses `completed`, `partial`, `insufficient_evidence`, `failed`, `cancelled`, `interrupted`; `grounding.decide_status`. A provider outage gives `failed`, never "no answer exists". | `tests/test_orchestrator.py::test_provider_faults`, `::test_nonexistent_entity_abstains`, `tests/test_grounding.py::test_decide_status`, Playwright fault test | Done |
| Small reproducible evaluation | `evals.py`, `predixion eval`, 8 scenarios, a one-pass baseline | `tests/test_evals.py`; `evals/results/`; [evaluation.md](evaluation.md) | Done |
| Report fields: question, short answer, findings, sources, confidence + explanation, limitations and assumptions, next steps, run ID, status, unresolved criteria, execution metadata | `contracts.ResearchReport` | Schema round-trip test; `tests/test_render.py`; sample reports in [samples/](samples/) | Done |
| The four assignment examples | Fixture scenarios plus live eval cases `vector_db_comparison`, `hr_tech_discovery`, `multi_agent_pros_cons`, `memory_comparison` | `tests/test_orchestrator.py::test_scenario_outcomes`; `evals/results/live-*.md` | Done |
| Criteria for "top" or "best" instead of arbitrary rankings | Plan instructions require explicit dimensions and assumptions; synthesis must not rank without criteria | Live eval comparison checks; sample report `vector-db-comparison` | Done |

## Engineering approach

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| One bounded workflow; code owns permissions, transitions, budgets, retries, acceptance | `orchestrator.ResearchRun`; `reliability.py` (`Budget`, `Deadline`, `call_with_retries`) | `tests/test_reliability.py`, `tests/test_orchestrator.py` budget tests | Done |
| LangGraph StateGraph | Plain asyncio orchestrator with explicit stages. The build prompt allows this if documented. Reasoning is in the README under "Why not LangGraph?". | — | Deviation |
| Python + uv lockfile, FastAPI, Pydantic, OpenAI Responses API, Tavily, async pooled clients, SQLite | `pyproject.toml`, `uv.lock`, `llm.py` (`AsyncOpenAI`), `tools.py` (`httpx.AsyncClient`), `store.py` | CI backend job | Done |
| React, TypeScript, Vite, Tailwind; Vitest and Playwright | `frontend/` | 24 Vitest tests, 7 Playwright tests | Done |
| Generate frontend API types from the backend contract where practical | `frontend/src/lib/types.ts` is hand-mirrored from `contracts.py` and lists only the fields the UI reads | Typecheck in `npm run build` | Partial: not generated |
| Structured JSON logging | `logs.py`, `runs.py` (`run accepted`, `run finished` with status, stop reason, duration, cost) | Manual inspection of server logs | Done |
| Docker and GitHub Actions | `Dockerfile`, `compose.yaml`, `.github/workflows/ci.yml` | Local `docker build` and a fixture-mode container run passed health, API, and export checks (see [submission.md](submission.md)). The CI result on GitHub has not been checked yet. | Partial |

## Inspectable research

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| Evidence records: source ID, safe URL, title, retrieval time, publication metadata, content hash, passage, claim link | `contracts.Source`, `contracts.Evidence`; IDs assigned by code (`S1…`, `E1…`) | `tests/test_grounding.py::test_evidence_ids_continue_after_existing`, `::test_reference_check_removes_fake_evidence_ids` | Done |
| Model selects IDs, never invents citations | Reference check drops unknown IDs; inline markers are parsed into IDs | `tests/test_orchestrator.py::test_fake_evidence_ids_are_dropped`, `tests/test_grounding.py::test_parse_draft_moves_inline_citations_into_evidence_ids` | Done |
| Coverage tracking (supported, missing, conflicting, stale) guiding follow-up | `grounding.compute_coverage` and `gap_criteria`; the follow-up stage receives the gaps | `tests/test_orchestrator.py::test_contradictory_evidence_is_reported`, `tests/test_grounding.py::test_polarity_conflicts_are_detected_per_entity` | Done |
| Entity eligibility checks | Eligibility criteria per entity; ineligible or unproven entities are excluded and listed separately | `tests/test_orchestrator.py::test_entity_without_eligibility_evidence_is_excluded`, `tests/test_grounding.py::test_discovery_comparison_keeps_only_listed_entities` | Done |
| Useful partial completion with stop reason and next steps | `snapshot_report`, `StopReason`, `decide_status` | `tests/test_orchestrator.py::test_page_budget_yields_partial_report`, `::test_model_attempt_budget_yields_partial_report` | Done |
| Coverage separate from confidence | `report.coverage` and `report.confidence` are computed separately (`grounding.assess_confidence`) | `tests/test_grounding.py` | Done |

## Workflow and contracts

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| Stages: validate → plan → search/read → filter → extract → assess → follow-up → synthesize → verify → finalize | `orchestrator.ResearchRun.execute`; stage events | `tests/test_api.py::test_run_streams_events_and_returns_report` | Done |
| Typed contracts: ResearchRequest, ResearchPlan, actions and tool args, ToolResult with per-item failures, Source, Evidence, Claim, ResearchState, ResearchReport, RunEvent, metrics | `contracts.py`. Research state is the `ResearchRun` object, not a separate model. | `tests/test_plan_contracts.py` | Done |
| Strict structured outputs | `prompts.py` schemas (closed objects, all fields required) | `tests/test_plan_contracts.py::test_structured_output_schemas_are_strict` | Done |
| Only known tools; plan validated before dispatch | `normalize_plan`, follow-up action allowlist | Plan and follow-up tests | Done |
| Concise, truthful progress events | `RunManager._emit`; UI shows only received events, with no percentages | Vitest `RunProgress` tests | Done |

## Model strategy

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| Configurable model; record model, SDK, prompt version, settings per eval | `RESEARCH_MODEL`, `PROMPT_VERSION`; eval JSON records model, reasoning effort, SDK version, prompt version, git commit, prices, limits | `evals/results/*.json` | Done |
| Initial candidate `gpt-6.1-sol`; optional low-cost `gpt-6-luna` | The owner asked for a lower-cost model, so the default is `gpt-6.1-terra` ($1 / $5 per Mtok). `gpt-6-luna` was evaluated against it. `gpt-6.1-sol` was not evaluated. | [evaluation.md](evaluation.md) | Deviation |
| Structured output + application validation; refusals, incomplete responses, invalid references | `llm.py` (strict `json_schema`, refusal and incomplete handling), `grounding.py` validation | `tests/test_providers.py::test_model_refusal_and_incomplete_are_not_retried`, `::test_model_output_that_is_not_json_is_malformed` | Done |
| No learned confidence model | Rule-based rubric only | — | Done |

## Tools and sources

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| `search_web`: validated query, constrained options, no provider answer synthesis | `contracts.SearchArgs`; Tavily request sets `include_answer: false` | `tests/test_providers.py::test_search_maps_results_and_sends_bearer_key` | Done |
| `read_sources`: selected validated URLs, per-item failures (including inside HTTP 200), size and batch limits | `tools.read_sources`, `TavilyClient.extract` | `tests/test_providers.py::test_extract_reports_partial_failures` | Done |
| Conservative canonicalization and dedupe | `urls.canonicalize_url` (drops tracking parameters only), shingle near-duplicates | `tests/test_sources_urls.py::test_canonical_url_dedupes_tracking_and_ordering` | Done |
| Source suitability; copies are not corroboration | Source tiers; first-party-only comparative criteria marked weak; independent-domain count in confidence | `tests/test_grounding.py` | Done |
| Retrieval time separate from publication time | `Source.retrieved_at` and `Source.published_at` | Report schema | Done |
| Unsupported formats, paywalls, inaccessible or empty pages, stale information; no bypassing | `has_non_text_extension`, `looks_paywalled`, short-page rejection, staleness window | `tests/test_sources_urls.py::test_paywall_detection` | Done |

## Grounding and confidence

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| Reference validity | `grounding.check_references` | `tests/test_grounding.py::test_reference_check_removes_fake_evidence_ids` | Done |
| Passage validity (normalized exact match) | `grounding.validate_evidence`, `quote_in_passage` | `tests/test_grounding.py::test_evidence_rejections`, `tests/test_orchestrator.py::test_fabricated_extraction_is_rejected` | Done |
| Semantic support, checked by a model verifier against only the cited passages | Verify stage | `tests/test_grounding.py::test_judge_rejects_real_quote_that_does_not_support_the_claim`, `tests/test_orchestrator.py::test_real_citation_that_does_not_support_the_claim_is_repaired` | Done |
| Check short answer, table cells, recommendations, not only findings | `grounding.enumerate_claims` and `finalize_draft` cover every claim location | `tests/test_grounding.py::test_finalize_removes_unsupported_claims_everywhere`, `tests/test_orchestrator.py::test_unsupported_short_answer_is_replaced_without_repair` | Done |
| Contradictions presented, not hidden | `conflicts` in the report; "Sources disagree" section | `tests/test_orchestrator.py::test_contradictory_evidence_is_reported`, Vitest | Done |
| High/Medium/Low rubric without fake probabilities | `grounding.assess_confidence` (rubric documented in [evaluation.md](evaluation.md)) | `tests/test_grounding.py` | Done |
| One bounded repair, then remove or qualify | `MAX_REPAIR_CYCLES=1` | Orchestrator repair test | Done |

## Security and privacy

Details are in [security.md](security.md).

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| Body, length, URL-count, parameter limits | `ResearchRequest`, body-size middleware | `tests/test_api.py::test_oversized_body`, `::test_rejected_requests` | Done |
| No shell, code, filesystem, or generic HTTP tools for the model | The model has no tools; code dispatches two fixed adapters | Design; `tests/test_plan_contracts.py::test_follow_up_actions_are_restricted` | Done |
| Secrets server-side only | `SecretStr` settings; not in `/api/config`, the frontend, logs, or fixtures | `tests/test_api.py::test_health_and_config`; gitleaks in CI | Done |
| Prompt-injection controls | `sources.screen_injection`; delimited untrusted blocks; no model-controlled tools, budgets, or destinations | `tests/test_orchestrator.py::test_injected_instructions_never_reach_the_model`, `tests/test_sources_urls.py::test_injection_sentences_are_removed` | Done (residual risk documented) |
| Fixed endpoints; URL validation; private and metadata destinations rejected; provider-side extraction | `config.py` constants; `urls.validate_public_url` | `tests/test_sources_urls.py::test_dangerous_urls_are_rejected`, `tests/test_orchestrator.py::test_unsafe_seed_url_is_ignored` | Done |
| Safe rendering; link protocols; CORS; security headers; loopback default; auth beyond local; scoping | React text rendering, `safeHttpUrl`, CSP and headers, `AUTH_MODE=token` with hashed tokens, owner-scoped queries | `tests/test_api.py::test_security_headers`, `::test_token_auth_scopes_runs_to_their_owner`, `tests/test_cli.py::test_serve_refuses_public_bind_without_auth`, `tests/test_render.py`, Vitest hostile-content test | Done |
| Redaction; no raw content logs by default; retention and deletion; fault injection off in production | `LOG_CONTENT=false`, `RUN_RETENTION_DAYS`, `DELETE /api/runs/{id}`, `fault_injection_allowed` | `tests/test_store_runs.py::test_purge_removes_only_old_terminal_runs`, `tests/test_api.py::test_fault_injection_is_refused_when_disabled` | Done |
| Dependency and secret scanning | `pip-audit`, `npm audit`, gitleaks, Dependabot | Local audit results in [security.md](security.md) | Done |

## Reliability and performance

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| Deadline, per-operation timeouts, bounded concurrency and queues, cancellation | `Deadline`, provider timeouts, `MAX_CONCURRENCY`, `MAX_CONCURRENT_RUNS`, `MAX_QUEUED_RUNS`, task cancellation | `tests/test_reliability.py`, `tests/test_store_runs.py::test_capacity_limit`, `::test_cancel_stops_a_running_run` | Done |
| Starting limits (2 rounds, 3 queries, 8 pages, 3 concurrent, 8 model attempts, 1 repair, 120 s with a 20 s reserve) | `config.Settings` defaults | — | Done |
| One retry owner; SDK retries off; backoff, jitter, Retry-After; no retry on auth or validation errors | `reliability.call_with_retries`; `AsyncOpenAI(max_retries=0)` | `tests/test_reliability.py` | Done |
| Token and cost ceilings with reservation and reconciliation; conservative on unknown usage; search costs included | `reliability.Budget` | `tests/test_reliability.py::test_settle_with_unknown_usage_keeps_the_worst_case`, `tests/test_orchestrator.py::test_cost_budget_is_enforced_before_the_first_call` | Done |
| Parallel retrieval, persistent clients, early dedupe, bounded passages, batched extraction, exact caching | `asyncio.gather` with a semaphore, shared `httpx` and OpenAI clients, `TTLCache` keyed on normalized query and URL | `tests/test_providers.py` | Done |
| Single-flight for duplicate in-progress work | Not implemented; duplicate submissions are handled by idempotency keys instead | — | Not done |
| Measure stage latency, first event, completion, usage, cost, retries, cache | `ExecutionMetrics` (stage timings, tokens, credits, retries, cache hits) | Eval results report latency and cost per case | Done |

## Persistence and API

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| Start, status and report, SSE progress, cancel, health and readiness, CLI | `/api/runs` routes, `/healthz`, `/readyz`, `predixion ask` | `tests/test_api.py`, `tests/test_cli.py` | Done (paths under `/api/runs`; see README) |
| Validated run IDs; scoped idempotency; conflicting reuse rejected | `RUN_ID_PATTERN`; owner-scoped unique index; `409 idempotency_conflict` | `tests/test_api.py::test_unknown_and_malformed_run_ids`, `tests/test_store_runs.py::test_idempotency_is_scoped_to_owner_and_request` | Done |
| Bounded event buffers and connections; reconnect without restarting the run | `MAX_EVENTS_PER_RUN`, `MAX_SSE_PER_RUN`, `MAX_SSE_TOTAL`, `Last-Event-ID` replay | `tests/test_store_runs.py::test_event_cap_keeps_terminal_events`, Vitest reconnect test | Done |
| Restart behavior defined | Marked `interrupted` on next start; graceful shutdown stores a snapshot report with evidence gathered so far. No checkpoint resumption. | `tests/test_store_runs.py::test_restart_marks_abandoned_runs_interrupted`, `::test_shutdown_interrupts_active_runs` | Done |

## Interface

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| White-and-black design, brand, tagline, copy, navigation, CTAs, no invented claims | `frontend/src/pages/Landing.tsx`, `Layout.tsx` | Playwright landing test | Done |
| Restrained 3D evidence cards with reduced-motion support and offscreen pause | `EvidenceStack.tsx` (CSS 3D, `IntersectionObserver`, `prefers-reduced-motion`) | Playwright landing test (renders, no horizontal overflow, axe) | Done |
| Workspace: examples, live/fixture modes, plan and stages, answer, citations with evidence drawer, coverage, conflicts and missing evidence, confidence, next steps, execution details, cancel, retry, export | `Workspace.tsx`, `Report.tsx`, `EvidenceDrawer.tsx`, `RunProgress.tsx`, `QuestionForm.tsx` | Vitest component tests; Playwright flows | Done |
| States: empty, loading, reconnecting, completed, partial, insufficient, error, cancelled; no fake percentages | `useRun.ts`, `RunProgress.tsx` | Vitest `RunProgress`; Playwright fault test | Done |
| Keyboard, focus, labels, contrast, responsive, reduced motion | Native `<dialog>` with focus return, labelled controls | axe (WCAG 2.1 AA tags) in Playwright on desktop and mobile; no manual screen-reader pass | Partial |

## Testing, evaluation, submission

| Requirement | Implementation | Validation | Status |
|---|---|---|---|
| Listed test categories (plan validation, contracts, filtering, fake IDs and quotes, unsupported claims, contradictions, injection, URLs and rendering, provider errors, partial extraction, budgets, retries, cancellation, duplicates, restart, browser flows) | `tests/`, `frontend/src/**/*.test.*`, `frontend/e2e/` | 191 backend tests pass (1 live test skipped); 24 Vitest; 7 Playwright | Done |
| ≥8 eval scenarios, including the four examples, nonexistent, ambiguous, contradictory, provider failure | `src/predixion/fixtures/scenarios/*.json`, `evals.py` | `evals/results/` | Done |
| One-pass baseline, same model; supported findings, coverage, abstention, latency, cost; live separate from fixture | `evals.run_baseline` | [evaluation.md](evaluation.md) | Done |
| LLM judge cannot certify; manual inspection; no false attribution | Lexical scorer; representative claims inspected by the development assistant (not the owner) | [evaluation.md](evaluation.md) | Done |
| Submission artifacts (README, Mermaid diagram, docs, samples, demo script, AI_USAGE, submission notes, CLAUDE.md, CI, lockfiles, `.env.example`, `.gitignore`, packaging) | Repository root and `docs/` | — | Done, except that the demo video is still to be recorded by the owner |

## Optional and stretch

| Item | Status |
|---|---|
| Deployment | Not done (optional) |
| Checkpoint resumption | Not done; runs are marked interrupted instead |
| Generated frontend types | Not done; types are hand-mirrored |
| Second search provider | Not done; the adapter interface allows it |
