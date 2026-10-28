# Independent audit

An independent verification and hardening review of Predixion AI, run after the build was complete.

| | |
|---|---|
| Date | 2026-10-28 |
| Reviewer | Claude Code in a cloud session, Claude Fable 5.1 model (an AI, not the owner) |
| Starting commit | `ca97a75` on `main` (the cloud feature branch pointed at the same commit); working tree clean |
| Final tested code commit | `4ffdd3d` (the first fixes are in `dcbb588`) |
| Documentation-only commits after it | one, recording the live results below (earlier documentation commits sit between the two code commits) |
| Runtime used for the review | Linux container, Python 3.13.17, uv 0.11.32, Node.js 22.22.0, npm 10.9.4, Playwright 1.64.1 with the container's preinstalled Chromium 1243 |
| Credentials | `OPENAI_API_KEY`, `TAVILY_API_KEY`, `GROQ_API_KEY` were present as environment variables and were never printed. All three accepted the live calls. |
| Network | Outbound HTTPS goes through the sandbox's egress proxy. It first refused `api.openai.com`, `api.groq.com` and `api.tavily.com` (HTTP 403 on CONNECT); the owner then allowed the three hosts, and the live checks in section 8 ran. |
| Docker | Client 29.9.2 present, no daemon. The Docker build is **BLOCKED** locally; it passed in GitHub Actions on `ca97a75` and again on the audit commits (run 23 and later, all four jobs green). |

**Verdict: ready for submission with stated limitations.** The application does what the assignment asks, every documented check passes from a clean container, the live path works against the real providers, and four real defects found during the review are fixed with regression tests. What remains is human work: record the demo video, give evaluators repository access, and read the documents the owner is expected to explain.

Status values in the tables: **PASS** (verified by running or inspecting it), **FAIL**, **BLOCKED** (could not be verified in this environment), **N/A**.

## 1. Baseline

Read in full: the assignment brief (via the build and audit briefs that restate it), `CLAUDE.md`, `README.md`, `AI_USAGE.md`, every file in `docs/`, `pyproject.toml`, `uv.lock`, `frontend/package.json`, `.github/workflows/ci.yml`, `Dockerfile`, `compose.yaml`, `.env.example`, and every backend module, frontend module, and test file.

Remote state at the start: repository private, default branch `main`, two remote branches (`main` and a Dependabot branch whose change was already on `main`), one open Dependabot pull request (superseded), CI green on `ca97a75` for all four jobs (backend, frontend, secrets scan, Docker). At the owner's request the Dependabot pull request was closed, the audit work was merged into `main`, and the audit commits were re-authored under the owner's identity. A temporary branch `main-reauthored` (same commit as `main`) could not be deleted from the session, because its git gateway refuses ref deletions; the owner deletes it.

## 2. Assignment requirements

| Requirement | Implementation evidence | Verification performed | Result | Remaining action |
|---|---|---|---|---|
| A real agentic workflow | `orchestrator.ResearchRun.execute`: plan, up to 2 rounds of search, filter, read, extract, assess, model-chosen follow-up, synthesize, verify, repair, finalize | Traced the code; ran fixture runs and watched the stage events; `tests/test_orchestrator.py` | PASS | – |
| At least two distinct tools | `tools.ToolRunner.search_web` (Tavily Search) and `read_sources` (Tavily Extract), separate endpoints and result shapes | `tests/test_providers.py` with `httpx.MockTransport`; live runs in section 8 used both (3–5 searches and 8 pages read per run) | PASS | – |
| Task-dependent tool selection | Follow-up stage: the model picks `search_web` or `read_sources` from an allowlist per gap; code validates and caps (`_validate_actions`); rule-based fallback when the model is unavailable | `tests/test_plan_contracts.py::test_follow_up_actions_are_restricted`, `::test_follow_up_respects_query_cap` | PASS | – |
| Visible planning and orchestration | `plan` event with criteria and queries; `stage` events; UI stage list, plan panel and activity log; CLI prints stages | Playwright run test; screenshots in the review session | PASS | – |
| Relevant retrieval and source filtering | URL safety, canonical de-duplication, non-text filter, low-relevance filter, paywall and short-page rejection, exact and near-duplicate content detection, per-domain cap, source tiers | `tests/test_sources_urls.py`; audit probe: a copy of a page on a second domain was marked `duplicate` and never counted as an independent source | PASS | – |
| Structured synthesis with sources | `contracts.ResearchReport`; every claim carries evidence IDs that resolve to quotes with source, date, and hash | Schema round-trip test; sample JSON files checked: 0 invalid references in all three | PASS | – |
| All seven required answer fields | `question`, `short_answer`, `key_findings`, `sources`, `confidence` (+ explanation), `limitations` + `assumptions`, `next_steps`; also `run_id`, `status`, `unresolved_criteria`, `execution` | `tests/test_render.py`; Markdown and JSON export checked in the browser | PASS | – |
| Timeouts | Global `Deadline` with a finalization reserve; per-operation timeouts bounded by time left; hard timeout in the run manager | `tests/test_reliability.py`; audit probe with a 9 s search under a 10 s deadline | PASS, after fix (queued runs lost deadline time; see [Defects](#defects-fixed)) | – |
| Retries | One owner (`call_with_retries`); SDK retries off; backoff with jitter; `Retry-After` honored and capped; no retry on auth, quota or validation errors; fallback to the next model instead of retrying when one exists | `tests/test_reliability.py`, `tests/test_routing.py` | PASS | – |
| Malformed output handling | Strict JSON schemas; non-JSON and non-object outputs classified `malformed_response`; refusals and truncation classified and not retried; every field re-validated and bounded in code | `tests/test_providers.py`, `tests/test_plan_contracts.py`, fault injection `model: malformed` | PASS | – |
| Hallucination controls | Quote must appear in the offered passage; citations must resolve to this run's IDs; model verifier judges each claim against only its quotes; one repair, then removal; entities listed only with every eligibility condition met | `tests/test_grounding.py`, `tests/test_orchestrator.py` adversarial tests; sample reports inspected by hand (below) | PASS | Verification checks claims against quotes, not quotes against the world (documented) |
| Prompt-injection awareness | Model has no tools; page text wrapped in `<untrusted_*>` elements with delimiters escaped; instruction-like sentences removed; follow-up reads name source IDs only; budgets and destinations never model-controlled | `tests/test_orchestrator.py::test_injected_instructions_never_reach_the_model`; audit probe with injection in a title, a snippet and a tool error message: none reached the model unfenced | PASS | Residual answer-contamination risk documented in `docs/security.md` |
| Deterministic output structure | Pydantic contracts with `extra="forbid"`; IDs assigned by code; Markdown export escapes untrusted text | Schema tests; `tests/test_render.py` | PASS | – |
| Tracing | Numbered, persisted events; stage timings, model attempts, retries, fallbacks, tokens, credits, cost per run; structured JSON logs without content | Event stream read via the API; logs seen while serving | PASS | – |
| Cost and latency decisions | Per-run token and cost reservation before each call, reconciled afterwards; conservative when usage is unknown; Tavily credits counted; cheaper models routed for small tasks; measured in `docs/evaluation.md` | `tests/test_reliability.py` budget tests; `test_cost_budget_is_enforced_before_the_first_call` | PASS | – |
| Evaluation document with ≥5 queries, expected behavior, actual outcomes, strengths and failures | `docs/evaluation.md`, 8 cases, expected vs actual per case, strengths and failures sections, raw results in `evals/results/` | Fixture suite re-run from a clean container: 20/20 agent checks, identical to the committed result. Two live cases re-run in this review (section 8); the full live suite was not repeated. | PASS | – |
| Two or three sample outputs | `docs/samples/`: four live reports labeled with mode, date, model and prompt version, generated by the app's exporter (the fourth, an abstention on a nonexistent product, was saved during this review) | Headers checked; references validated; claims read against quotes | PASS | – |
| README: setup, architecture, tradeoffs, limitations, production considerations | `README.md` with a Mermaid diagram and explicit answers to the assignment's questions | Followed the quick start from a clean container | PASS | – |
| 3–5 minute demo with a success and a failure case | `docs/demo-script.md` covers both | No video exists | BLOCKED (human task) | Owner records and links it in `docs/submission.md` |
| Repository accessible to evaluators | Repository is private (checked through the GitHub API during the review) | – | FAIL until access is granted | Owner adds evaluators as collaborators or makes the repository public |
| Truthful AI-tool-use disclosure | `AI_USAGE.md` names the tools, models, what they did, what was validated, and now this review session | Read and extended | PASS | – |

Owner-requested features beyond the assignment (Groq routing, the 3D landing element, token auth, export, retry) and optional stretch goals (long-term memory, deployment, checkpoint resumption, generated frontend types) are not scored as assignment failures. The build's own traceability is in `docs/requirements.md`.

## 3. Reproduction from a clean environment

Every command below was run in this review. Numbers are from the final tested commit unless stated.

| Check | Command | Result |
|---|---|---|
| Lockfile install | `uv sync --frozen` | PASS |
| Lint and format | `uv run ruff check . && uv run ruff format --check .` | PASS |
| Backend tests | `uv run pytest` | PASS: 219 passed, 1 skipped (the opt-in live test) |
| Fixture evaluation | `uv run predixion eval --mode fixture` | PASS: agent 20/20 checks, 34/35 claims, 16/27 criteria; exit 0 |
| CLI | `uv run predixion ask … --mode fixture`, `samples`, `eval` | PASS (exercised by `tests/test_cli.py` and the fixture evaluation) |
| API | `predixion serve` in fixture mode, then the Playwright suite and manual requests | PASS |
| Frontend install and build | `npm ci && npm run build` | PASS (TypeScript check and Vite build, 277 kB JS before gzip) |
| Frontend unit tests | `npm test` | PASS: 25 Vitest tests |
| Browser tests | `npm run e2e` | PASS: 7 Playwright tests including axe scans, desktop and mobile. Note: the project pins Playwright 1.64.1, whose browser build (1248) was not installed in the sandbox; the suite was run with a throwaway config pointing at the preinstalled Chromium 1243. The repository's own command is unchanged. |
| Frontend development path | `vite.config.ts` proxies `/api` to the backend | Inspected; not started interactively |
| Docker | `docker build` | BLOCKED locally (no daemon). The GitHub Actions `docker` job passed on `ca97a75`. |
| Dependency advisories | `pip-audit` on the hash-locked export; `npm audit --audit-level=high` | PASS: no known vulnerabilities on 2026-10-28 |
| Secret scan | gitleaks runs in CI (passed on `ca97a75`); `.env.example` has empty values; `git grep` for key prefixes found nothing | PASS |
| Missing credentials | `GET /api/config` reports `live_available: false`; the UI disables the live option with an explanation; `POST /api/runs` with `mode: live` returns `503 live_unavailable`; the CLI exits 2 with the missing variable names | PASS |
| Fixture mode labeling | Mode badge, "Fixture demo · synthetic sources" text, a limitation line in every fixture report, a note in the Markdown export, `fixture: true` on every source, and a caveat in the evidence drawer | PASS |
| Backend and frontend contracts agree | Script compared every interface in `frontend/src/lib/types.ts` with `contracts.py`: no TypeScript field is missing from the Pydantic models, and the `RunStatus`, `StopReason`, `Stage`, `CoverageStatus`, `SupportVerdict` and `EventType` enums match exactly | PASS |
| CI matches documented commands | `.github/workflows/ci.yml` runs the same commands as `CLAUDE.md` and the README | PASS |

The existing tests were read for meaning, not only counted. They assert outcomes (statuses, stop reasons, removed claims, rejected evidence, replayed sequence numbers, 404s for other owners), not implementation details, and the adversarial ones inject real failure modes. No test was weakened.

## 4. Architecture and resource behavior

Traced one question end to end through `execute → _plan → _research → _run_round → _search_all / _select_candidates / _read / _accept_page → _extract_round → _coverage → _follow_up → _conclude → _synthesize → _verify → _repair → finalize_draft → _build_report`.

| Property | Finding | Result |
|---|---|---|
| Every loop terminates | The round loop is bounded by `max_rounds` (≤4) and also stops on criteria satisfied, diminishing returns, deadline, page budget, or no actionable gaps. Retries are bounded by `RetryPolicy.max_attempts` and the deadline. Model attempts are bounded by `MAX_MODEL_ATTEMPTS`. The SSE loop ends on the terminal event or disconnect. | PASS |
| Retries cannot multiply across layers | SDK clients are built with `max_retries=0`; the Tavily adapter never retries; `call_with_retries` is the only loop. With a fallback model available, a failed attempt moves to the next model instead of retrying. | PASS |
| Attempts, tokens, spend reservations and deadlines stay bounded under concurrency | Budget bookkeeping is synchronous (no await between check and update). Load probe: 25 fixture runs submitted at once with 4 slots and 16 queue places → 20 accepted, 5 refused with `429`, all 20 completed, no run left active. | PASS |
| Queued runs keep their deadline | **Defect found and fixed**: the deadline and duration clock started when a run was admitted, not when it got a slot (probe: a run queued 4 s behind another reported 4.03 s elapsed for 8 ms of work). `Deadline.restart()` is now called at execution start. | PASS after fix |
| Reserved finalization time is enforced | `Deadline.op_timeout` refuses research operations once only the reserve is left and lets finalizing calls use it; the round loop will not start a round with under 25 s of research time. | PASS |
| Cancellation propagates | `cancel()` sets a flag and cancels the task; the orchestrator's awaits (`gather`, `wait_for`) propagate `CancelledError`; pending reservations are settled; a snapshot report with the evidence gathered so far is stored; a run cancelled while queued is also finished (`_ensure_finished`). | PASS (`test_cancel_stops_a_running_run`) |
| Partial results survive unrelated failures | A page that fails leaves the others usable (`test_partial_extraction_still_completes`); a failed search query is logged and the others' hits are registered; extraction failure in one round keeps the previous rounds' evidence; synthesis or verification failure yields an evidence-only report. | PASS |
| One failed concurrent task does not discard all results | In `_search_all`, results are gathered with `return_exceptions=True` and hits are registered query by query; only `BudgetExhausted` / `DeadlineReached` end the round, and the hits registered before that point remain. Hits from queries that completed after the failing one in list order are not registered. In practice the budget check runs at task start in list order, so the exhausted query is the last one. | PASS (minor ordering caveat, not fixed) |
| Event buffers, queues, connections and state are bounded | Events per run capped (terminal events always kept); SSE streams capped per run and in total; subscriber queues are unbounded `asyncio.Queue`s but each run emits at most `MAX_EVENTS_PER_RUN` events; `TTLCache` is LRU with a size cap; `httpx` pool limits set; active runs are removed from memory when finished. | PASS |
| Reconnection does not start duplicate paid research | Reconnect is a `GET` of the event stream with `Last-Event-ID`; nothing on that path creates a run. Starting a run is idempotent by key. | PASS (`test_run_streams_events_and_returns_report`, Vitest reconnect test) |
| Idempotency scoped and mismatches rejected | Unique index on `(owner, key)`; same key with a different body → `409`. | PASS |
| Restart behavior matches the claim | Active runs are marked `interrupted` on the next start and get a terminal event; graceful shutdown stores a snapshot; nothing claims resumption. | PASS |
| Worker crashes do not leave runs active forever | Any exception in `_run` ends in `_finish` with a `failed` status; a crash of the whole process is handled by `mark_interrupted` at the next start. There is no second worker, so a run can stay `running` only while the process is down. | PASS |
| Blocking I/O on the event loop | SQLite is used synchronously under a lock. Measured: `append_event` on disk takes about 0.5 ms (two autocommit statements with fsync). At the configured caps (4 runs × ≤400 events) this is tolerable; on a slow disk or at higher caps it would add latency to every coroutine. Not changed. | PASS with a note (deployment-dependent) |
| Exactly-once execution, durable recovery | Not claimed anywhere; the README states at-least-once event delivery and in-process, non-durable execution. | PASS |

## 5. Grounding and research quality

Adversarial fixtures run during the review (probe scripts, not committed, re-creating each case against fixture providers), plus the committed tests:

| Case | What happened | Result |
|---|---|---|
| Fabricated source or passage ID | Rejected `unknown_passage` (`test_fabricated_extraction_is_rejected`); fabricated evidence IDs in claims dropped by `check_references` (`test_fake_evidence_ids_are_dropped`) | PASS |
| Fabricated quotation | Rejected `quote_not_found` after conservative normalization; ellipses refused | PASS |
| Real quotation that does not imply the claim | Verifier returns `not_supported`; one repair; still unsupported → removed (`test_real_citation_that_does_not_support_the_claim_is_repaired`) | PASS |
| Claim supported only by an outdated version | Criterion with `needs_freshness` and a 365-day window, only a 2021 source → coverage `stale` | PASS |
| Missing publication dates | Same criterion with an undated source → `stale`; the evidence drawer shows "Publication date unknown" | PASS |
| Unsupported assertion in the short answer despite valid finding citations | Short answer replaced with a standard notice and listed under removed claims (`test_unsupported_short_answer_is_replaced_without_repair`) | PASS |
| Conflicting sources | Opposite polarity on the same criterion and entity → coverage `conflicting`, a conflict entry, status `partial`, confidence not High (`test_contradictory_evidence_is_reported`) | PASS |
| Duplicate articles that appear independent | A copy of a page served from a second domain was marked `duplicate` ("Same content as S3"), never read, and not counted as an independent domain | PASS |
| Marketing language presented as comparative performance | Comparative criterion supported only by first-party evidence → `weak`; the synthesis prompt requires vendor claims to be attributed | PASS |
| Entity failing one eligibility criterion | Excluded with a reason; included entities need every condition `met` with evidence (`test_entity_without_eligibility_evidence_is_excluded`); the fixture evaluation's `eligibility_backed` check | PASS |
| Irrelevant page with a high provider score | Not filtered before reading (the filter drops only low-score, zero-overlap hits); it is read, and the extraction step returns nothing usable from it, so it adds no evidence. Costs one page slot. | PASS with a note |
| Nonexistent company or unanswerable question | `nonexistent_entity` scenario ends `insufficient_evidence` with no findings; the plan includes an existence criterion | PASS |
| Oversized page | Page content clipped at 60,000 characters before chunking (`clean_content`) | PASS |

Confidence is computed by `grounding.assess_confidence` from coverage, verifier verdicts, independent domains, first-party share, conflicts and staleness. It is not the model's self-rating, and coverage and confidence are separate fields. Two weaknesses already recorded in `docs/evaluation.md` stand: a two-part criterion can count as supported when one part is established, and High does not require a high-suitability source. They were left as documented limitations rather than retuned blind, because the live suite could not be re-run here to measure a change.

Follow-up research targets gaps: the follow-up prompt receives only the unmet criteria, previous queries and unread candidates; near-repeats of earlier queries are discarded in code; a round that adds no evidence stops the run (`diminishing_returns`); budget and deadline stops are tested.

Manual claim inspection (by the reviewer, an AI): the first four findings of the HR-tech and SQLite sample reports were read against their quoted passages. All eight say only what the quotes say, including the hedges ("does not establish", "conservative estimate, not a hard limit"). The lexical scorer marks several of them unsupported, which confirms the documented bias of that scorer rather than a grounding problem. The vector-database report was inspected in the build session. The live run of the same question in this review (section 8) produced 12 claims, all verified; its five findings were read against their quotes and say only what the quotes say, including "the reviewed evidence cannot establish that they are the top three".

## 6. Security review

Tested against the local fixture instance and with probe scripts; nothing outside the project was probed.

| Area | Finding | Result |
|---|---|---|
| Prompt injection in page text, titles, snippets, tool errors | Injection text in a title, a snippet and an extraction error message was fenced (`<untrusted` → `&lt;untrusted`, quotes stripped in attributes) and the instruction sentence in page text was removed; no model input contained the raw payload | PASS |
| Changing tools, budget, instructions or objective | Not reachable: the model has no tools, follow-up actions are allowlisted and validated, budgets and endpoints are constants or server settings, the question is fixed for the run | PASS |
| Forwarding unrelated private content via follow-up searches | The follow-up prompt contains only the question, gaps, previous queries, entities and public snippets; the server holds no other user content in the run | PASS |
| Oversized requests and content | 64 KiB body cap (`413`), question ≤1000 characters, ≤3 seed URLs, page text clipped at 60,000 characters, passages ≤1,100 characters | PASS |
| Unsafe URLs | `validate_public_url` rejects non-http(s), credentials, non-default ports, whitespace and backslashes, percent-encoded hosts, private/loopback/link-local/multicast/reserved IPv4 and IPv6 (mapped, 6to4, NAT64, Teredo, site-local, zone IDs), `localhost`/`.local`/`.internal`/metadata names, single-label and numeric-TLD hosts | PASS (`tests/test_sources_urls.py`) |
| Redirect and DNS-rebinding defenses | N/A: the server never fetches pages; Tavily does. Documented honestly, with the hardening list that would be needed if direct fetching were added. | N/A |
| Malicious HTML, script URLs, citation rendering | React renders text only; `safeHttpUrl` allows only http(s); Markdown export escapes syntax; CSP without inline scripts; Vitest hostile-content test | PASS |
| Secret leakage | Keys are `SecretStr`, absent from `/api/config`, reports, events, the frontend bundle (checked: no key-shaped strings in `dist/`; the only provider mention is the `tavily_credits` field name), logs (content off by default), fixtures and git history (gitleaks). Note: an unexpected exception is logged with a traceback (`logger.exception`), which could include request values in a Pydantic validation message. Low risk; not changed. | PASS with a note |
| Cross-session access | Every run read, stream, cancel, export, delete and idempotency lookup is owner-scoped; other owners get `404` | PASS (`test_token_auth_scopes_runs_to_their_owner`, `test_other_owners_cannot_see_a_run`) |
| Authentication, CORS, debug exposure | Loopback bind by default; non-loopback refused without token auth unless explicitly allowed; constant-time token comparison on SHA-256 hashes; CORS limited to configured origins without credentials; OpenAPI docs disabled in production; fault injection ignored in production (`fault_injection_allowed` returns False with `PREDIXION_ENV=production` even when the flag is on; verified) | PASS |
| Untrusted provider endpoints | Constants in `config.py`; no environment variable can redirect traffic | PASS |
| Retention and deletion | Terminal runs older than `RUN_RETENTION_DAYS` purged at start and hourly; `DELETE /api/runs/{id}`; cache is in memory with TTLs | PASS |

Defenses that belong to the application: everything above. Defenses that depend on others: Tavily's own fetching network (SSRF on their side), OpenAI's, Groq's and Tavily's data handling, TLS termination and rate limiting at any edge in front of the server, and disk protection of the SQLite file.

Suggestions, not defects: the SSE slot counter is acquired before the response body generator starts and released in the generator's `finally`; a client that disconnects before the first byte could in principle leak one slot. Not reproduced.

## 7. Failure handling

| Injected failure | Behavior | Result |
|---|---|---|
| HTTP 429 with `Retry-After` | Retried after the header's delay (capped at 20 s); if every attempt fails, `failed` / `provider_unavailable` | PASS |
| Temporary 5xx | Retried with jittered backoff, bounded by attempts and the deadline | PASS |
| Invalid credentials | Classified `auth`, never retried; the provider is skipped for the rest of the run; `failed` / `provider_auth_error` | PASS |
| Connection errors and timeouts | Classified and retried; unknown usage is billed at the worst case and flagged `cost_uncertain` | PASS |
| Malformed JSON and missing fields | `malformed_response` (retryable once a model is left); missing fields bounded and defaulted in code | PASS |
| HTTP 200 with per-item extraction failures | Recorded per item, other pages used; if every page fails, `insufficient_evidence` / `no_relevant_sources` with the count | PASS |
| Empty or irrelevant results | `insufficient_evidence` / `no_relevant_sources`; nothing invented | PASS |
| Model refusal, incomplete output, schema-valid but semantically invalid output | Refusal and truncation not retried and not sent to another model; semantically invalid outputs (unknown IDs, quotes not in passages, unknown criteria) rejected item by item | PASS |
| Budget exhaustion before and during parallel work | Before the first call: `failed` / `budget_exhausted` with zero attempts. During research: the evidence collected so far is kept and the run ends `partial`. **Fixed**: after pages were read but before extraction, the run used to end `insufficient_evidence`; it now ends `failed` with the budget reason. | PASS after fix |
| Deadline before any page is read | **Fixed**: used to be `insufficient_evidence` / `no_relevant_sources`; now `failed` / `deadline_reached` | PASS after fix |
| User cancellation | `cancelled` with a snapshot report and a terminal event; repeat cancel harmless | PASS |
| Client disconnect and reconnect | Stream resumes after `Last-Event-ID`; duplicates discarded client-side; no new run started | PASS |
| Duplicate requests | Idempotency key returns the same run; different body → `409` | PASS |
| SQLite contention or persistence failure | One connection under a lock with `busy_timeout`; an event that fails to persist is logged and the run continues (`_emit` catches exceptions); a report that fails to save would surface as an unhandled exception in `_finish`. Not fault-injected. | PASS (partially inspected, not injected) |
| Process interruption | `interrupted` on next start with a terminal event; graceful shutdown stores a snapshot | PASS |
| All sources failing | `insufficient_evidence` / `no_relevant_sources` with the count of failed pages when extraction returned per-item failures; `failed` / `provider_unavailable` when the provider itself was down | PASS |

In every case the report carries a readable explanation, no findings are invented, and confidence is Low.

## 8. Evaluations

| Suite | Conditions | Result |
|---|---|---|
| Fixture, 8 cases, agent and baseline | Offline, scripted model, re-run in this review | Agent 20/20 checks, 34/35 claims (circular, see `docs/evaluation.md`), 16/27 criteria, median latency 0.0 s, $0. Baseline 11/14, 16/20, 7/27. Identical to the committed `evals/results/fixture.md`. |
| Live smoke while the network was blocked (same 2 cases) | Real keys present; sandbox refused all three provider hosts | Both runs `failed` / `provider_unavailable` in about 2 s after the fallback chain (Groq 120b → Groq 20b → OpenAI, 5 attempts, 2 retries); estimated cost $0.045 each is the conservative worst-case reservation for connection errors, flagged `cost_uncertain`; nothing was billed. PASS as failure handling; kept out of the repository. |
| Live smoke, 2 cases (`vector_db_comparison`, `nonexistent_product`), no baseline, `--max-spend 0.30`, after the hosts were allowed | `gpt-6.1-terra` low effort, Groq routing on (`plan`, `follow_up` on `openai/gpt-oss-120b`), prompt `2026-10-28.3`, commit `5e37466`, 2026-10-28 17:02 UTC; [`evals/results/audit-live-smoke.md`](../evals/results/audit-live-smoke.md) | Vector: `partial` / `rounds_exhausted`, Low confidence, 12 of 12 claims verified, comparison table with 3 rows (Milvus, pgvector, Weaviate), 1 of 5 planned criteria supported, 52 s, $0.072, 3 searches, 8 pages. Checks 3/3. Nonexistent product: `partial`, 1 of 4 claims verified (3 removed), 27 s, $0.063; check `abstains` FAILED, which exposed defect D4 below. Suite $0.135. |
| Live recheck of `nonexistent_product` after the D4 fix, `--max-spend 0.15` | Same settings, commit `5e37466` plus the fix; [`evals/results/audit-live-nonexistent-recheck.md`](../evals/results/audit-live-nonexistent-recheck.md) | `insufficient_evidence` / `diminishing_returns`, Low confidence, 8 pages read, no evidence extracted, no answer invented, 14 s, $0.056. Check 1/1. This run abstained through the zero-evidence path, so the new status rule is proven by its unit test rather than by this run. Saved as `docs/samples/nonexistent-product`. |
| Opt-in live test | `PREDIXION_LIVE_TESTS=1 uv run pytest tests/test_live.py` | PASS: one live run on an explainer question, within its $0.20 cap, with every finding citing evidence that exists |
| Live, all 8 cases, agent vs baseline, both models | From the build session on 2026-10-28, single runs each | Not re-run. Numbers and caveats stand as written in `docs/evaluation.md`. |
| Concurrency mechanics under mocked load | 25 submissions, 4 slots, 16 queue places, fixture providers | 20 accepted, 5 refused with `429`, all completed in 0.2 s; separate from live provider latency |

Sample sizes are small and single-run; no p95 is claimed. The lexical judge is a lower bound; representative claims were read by hand (section 5). Total live spend in the review: about $0.33 estimated, plus about $0.09 of worst-case reservations for the blocked attempts that were never billed.

## 9. Interface

Checked in a real browser (Chromium, Playwright) against the fixture-mode server with the built frontend.

| Check | Result |
|---|---|
| White background, near-black text | `rgb(255,255,255)` and `rgb(10,10,10)` measured on `body` |
| Brand and tagline | "Predixion AI"; `h1` "Clear answers. Evidence you can inspect."; supporting copy present |
| Restrained 3D element | CSS 3D card stack, `aria-hidden`, does not cover content; no canvas or WebGL is used, so the static fallback requirement does not apply |
| Reduced motion | With `prefers-reduced-motion: reduce` the card animation name is `none` |
| No continuous offscreen rendering | `IntersectionObserver` adds `is-paused` offscreen; animations are CSS transforms only |
| Real backend actions | Sample run, fixture run, cancel, retry, export all call `/api/runs` endpoints; export files match the stored report (`test_export_formats`) |
| States | Empty, loading, live, reconnecting, completed, partial, insufficient evidence, failed, cancelled, interrupted and not-found all have distinct rendering (`RunProgress`, `Report`, `Workspace`); no numeric progress is simulated |
| Citation drawer | Opens on click or Enter, shows the quote, claim, criteria, source, dates, caveats and a safe link; Escape closes it and focus returns to the citation |
| No fabricated content | No testimonials, logos, statistics or certifications on the landing page; fixture runs are labeled four ways |
| Safe rendering | Text only, `safeHttpUrl` for every link, `rel="noopener noreferrer nofollow"` |
| Keyboard, labels, contrast | axe (WCAG 2.1 AA tags) passes on landing, report, error and failure pages at desktop and mobile; skip link, labelled controls, `aria-live` stage announcements |
| Layout | No horizontal overflow at 1366 px or 390 px on the landing page or the report |
| Not done | A manual screen-reader pass (already listed as a gap) |

Screenshots were taken during the review (landing desktop, landing mobile, landing with reduced motion, report desktop, report mobile, evidence drawer, failure state) and kept outside the repository.

## Defects fixed

All three are confirmed (reproduced before the fix, regression test added, test fails on the old code and passes on the new).

### D1. Queued runs lost deadline time — severity medium, confidence high

- **Observed.** `ResearchRun` is constructed when a request is admitted, and its `Deadline` and timing clocks started then. A run that waited in the queue behind others started research with part of its 120 s already spent, and its reported duration included the wait. With four slots and long live runs, a fifth run could reach its deadline before doing any work.
- **Reproduction.** Two runs with one slot, the first holding it for 4 s: the second reported `duration_ms = 4026` and `deadline.elapsed() = 4.03` for about 8 ms of work.
- **Root cause.** Clock start in `__init__` instead of at execution.
- **Fix.** `Deadline.restart()`; `ResearchRun.execute()` restarts the deadline, the performance timer and `metrics.started_at`.
- **Test.** `tests/test_store_runs.py::test_queued_run_keeps_its_full_time_limit`.

### D2. Budget stop before extraction reported as "insufficient evidence" — severity medium, confidence high

- **Observed.** With the cost ceiling reached after pages were read but before the extraction call, the run ended `insufficient_evidence` with "No usable evidence was found", and the UI said the sources did not support an answer. Nothing had been analyzed.
- **Reproduction.** Live prices with fixture providers and `MAX_COST_USD_PER_RUN=0.02`, or a model that raises `BudgetExhausted` on the extract task.
- **Root cause.** `_conclude` mapped "no evidence" to `insufficient_evidence` unless the stop reason was a provider failure.
- **Fix.** `CUT_OFF_STOP_REASONS` (provider outage, auth, deadline, budget, invalid model output, internal error): with no evidence these end `failed`, keeping the stop reason and saying the run stopped before any evidence could be extracted.
- **Test.** `tests/test_orchestrator.py::test_budget_stop_before_extraction_is_reported_as_failed`.

### D3. Deadline before any read relabelled "no relevant sources" — severity medium, confidence high

- **Observed.** A deadline reached during the first search produced `insufficient_evidence` / `no_relevant_sources`; the UI headline said no relevant sources were found while the detail said the deadline was reached.
- **Reproduction.** A 9 s search under a 10 s deadline, or a search that raises `DeadlineReached`.
- **Root cause.** The same branch overwrote the stop reason whenever nothing had been read.
- **Fix.** Same as D2; the overwrite now applies only when research actually ran and found nothing.
- **Test.** `tests/test_orchestrator.py::test_deadline_before_any_page_is_read_is_reported_as_failed`.

No fixture evaluation case changed status as a result (the fixture results re-run after the fix are identical).

### D4. Unanswered run labelled "partial" — severity medium, confidence high

- **Observed.** In the live smoke run, the nonexistent-product question ended `partial`. Verification had removed the short answer and two of three findings; the surviving finding only said the pages describe a different project; every required criterion was `missing` or `stale`. The UI would have shown "Partial answer" for a report that answered nothing, and the evaluation's `abstains` check failed.
- **Reproduction.** `evals/results/audit-live-smoke.md`, case `nonexistent_product`; deterministic unit reproduction in the new test.
- **Root cause.** `grounding.decide_status` returned `partial` whenever at least one claim was supported, without looking at whether the short answer survived or any required criterion was supported.
- **Fix.** When verification ran, the short answer failed, and no required criterion is supported, the status is `insufficient_evidence`. A surviving short answer or one supported required criterion still gives `partial`.
- **Test.** `tests/test_grounding.py::test_unanswered_report_with_only_a_caveat_finding_is_insufficient_evidence`. The fixture suite is unchanged (20/20); the live recheck abstained.

### Documentation

Corrected to match the code: the question length limit is 8–1000 characters (documents said 10–2000); the backend test count (191 → 216 at the end of the build, 219 now) and Vitest count (24 → 25). Added the status semantics to the README, this review to `AI_USAGE.md`, the audit outcome to `docs/evaluation.md`, `docs/requirements.md` and `docs/submission.md`.

## Suggestions (not fixed)

- Connection errors that never reach a provider are billed at the worst-case reservation. Conservative and flagged, but a network outage makes failed runs look expensive in the metrics.
- `_search_all` registers hits in query order and stops at the first budget or deadline exception; hits from later-ordered queries that had already completed are not registered. Rarely matters because the budget check runs at task start.
- Synchronous SQLite calls on the event loop (about 0.5 ms per event on this disk). Fine at the configured caps; move to a thread or batch commits before raising them.
- The confidence rubric could require at least one high-suitability source for High, and criteria with two parts could be split by the planner. Both need live measurement before changing.
- `logger.exception` on unexpected errors may include request values in Pydantic messages; consider trimming the message when `LOG_CONTENT` is off.
- Generate `frontend/src/lib/types.ts` from the Pydantic models to remove the hand-mirroring risk (currently in sync).

## Residual risks and untested behavior

- Live coverage in this review is three runs (two smoke cases and one recheck) plus the opt-in test; the full live suite numbers are still single runs from the build session.
- The Docker image was not built here; CI built it.
- A manual screen-reader pass has not been done.
- Grounding checks claims against quotes, not quotes against the world; a wrong page can produce a well-cited wrong claim.
- The evaluation set is small, was used during prompt development, and is scored lexically.
- No per-user quotas, rate limiting, or durable execution; these are listed as prerequisites for public use.
- SQLite persistence failures were inspected, not fault-injected.

## Concepts and tradeoffs the owner should be able to explain

- Why the model proposes and the code decides, and what that buys for prompt injection and cost control.
- The three grounding properties (reference validity, passage validity, semantic support) and why passage validity alone is not proof.
- The difference between coverage and confidence, and the rubric's known weaknesses.
- The status semantics: `completed`, `partial`, `insufficient_evidence` (a verdict about pages read), `failed` (could not research, including limit stops before any evidence), `cancelled`, `interrupted`.
- The single retry owner, budget reservation and reconciliation, worst-case billing on unknown usage, and why fallback attempts count toward the same limits.
- Why `/api/runs` with SSE instead of a blocking `/research` endpoint, and what "not durable, at-least-once events" means.
- Why Tavily does the fetching and what the URL checks do and do not control.
- What the lexical evaluation scorer can and cannot show, and why the agent's support rate is lower than the baseline's in that metric.
- Why Groq routing is used for small tasks and why its answer quality is not yet measured.

## Remaining human tasks

1. Record the 3–5 minute demo (happy path plus a failure case) following `docs/demo-script.md`, and add the link to `docs/submission.md`.
2. Grant evaluators access to the private repository, or make it public.
3. Delete the leftover `main-reauthored` branch on GitHub (it points at the same commit as `main`; the review session's git gateway refused the deletion).
4. Read `AI_USAGE.md`, the residual risks in `docs/security.md`, the caveats in `docs/evaluation.md`, and this file before presenting the work.
5. Choose a license.
