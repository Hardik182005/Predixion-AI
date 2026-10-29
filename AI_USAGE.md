# AI usage

This project used AI in two separate ways:
- **Development assistance** helped write the code and docs.
- **Runtime LLM use** is part of how the application works.

## Development assistance

**Tool:** Claude Code (Anthropic's CLI coding agent), with the Claude Opus 5.5 model selected.

**What it did, working from the owner's build brief:**
- **Planning:** proposed the architecture, contracts, and implementation order.
- **Code:** wrote the backend, frontend, CLI, evaluation harness, fixtures, Dockerfile, and CI workflow.
- **Tests:** wrote the backend tests (pytest), frontend unit and component tests (Vitest, Testing Library), and browser tests (Playwright with axe).
- **Evaluation:** ran the fixture and live suites. It also used the live results to find and fix three bugs:
  - comparison tables missing from comparison questions,
  - inline citation markers,
  - planner eligibility rules.
- **Documentation:** wrote this file, the README, and everything in `docs/`.

**How the work was checked during development (commands actually run):**
- `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`: 216 passed, 1 skipped at the end of the build session. The skipped test is the opt-in live test.
- `npm run build` (TypeScript check plus production build), `npm test` (25 Vitest tests), and `npm run e2e` (7 Playwright tests, including axe accessibility scans).
- `uv run predixion eval --mode fixture`: all 20 agent checks pass.
- Live evaluations with real OpenAI and Tavily calls. Results are in `evals/results/`, and spending was capped per run with `--max-spend`.
- `pip-audit` and `npm audit --audit-level=high`: no known vulnerabilities on 2026-10-28.
- `docker build` (Docker 29.6.2). The container was then run in fixture mode:
  - `/healthz` and `/readyz` responded, the UI was served, and Docker reported the container healthy.
  - It ran as a non-root user.
  - A research run through the API completed, and both exports worked.
- GitHub Actions: on 2026-10-28 the CI run for commit `31b8e31` passed all four jobs (backend, frontend, secrets scan, Docker build) on `main` and on `feature/research-agent`.

**What was not checked:**
- The demo video, which has not been recorded.

## Independent review session

**Tool:** Claude Code in a cloud session (claude.ai/code), with the Claude Fable 5.1 model selected, on 2026-10-28, starting from commit `ca97a75` on `main`. The full report is [docs/audit.md](docs/audit.md).

**What it did:**
- Read the assignment brief, the build brief, the repository instructions, every document, and the backend and frontend source.
- Re-ran every documented check from a fresh container: `uv sync --frozen`, ruff, pytest, the fixture evaluation, `npm ci`, `npm run build`, Vitest, Playwright (with the container's preinstalled Chromium), `pip-audit`, and `npm audit`.
- Wrote probe scripts (not committed) that reproduced three defects, then fixed them and added regression tests:
  - A run's time limit and duration clock started when the run was queued, not when it got an execution slot (`Deadline.restart`).
  - A cost stop after pages were read but before extraction was reported as `insufficient_evidence`.
  - A deadline stop before any page was read was relabelled `no_relevant_sources`.
  - A report whose short answer and required criteria all failed verification was labelled `partial` (found in a live run).
- Ran adversarial fixture probes for prompt injection in titles, snippets and tool errors, duplicate articles on different domains, oversized pages, vendor-only comparative claims, outdated and undated sources, conflicts, and fault injection in production.
- Verified the interface in a real browser at desktop and mobile widths, with and without reduced motion.
- Corrected documentation that disagreed with the code (question length limits, test counts) and wrote `docs/audit.md`.

**Live checks:** the sandbox's network policy first refused the OpenAI, Groq and Tavily hosts (the app reported `failed` / `provider_unavailable` as designed). After the owner allowed the hosts, the session ran the opt-in live test and three live evaluation runs (about $0.33 estimated), which exposed and fixed a fourth defect: an unanswered run labelled `partial` instead of `insufficient_evidence`. Those results are in `evals/results/audit-live-*.md` and `docs/samples/nonexistent-product.md`. Docker was unavailable in the sandbox; the Docker build was verified through the GitHub Actions runs.

**Review status.** The review session read representative claims in the committed sample reports against their quoted passages. That is again an AI checking AI output, not a human review.

**Review status.** The development assistant inspected representative live claims against their cited sources; see [docs/evaluation.md](docs/evaluation.md). That is an AI checking AI output, not an independent human review. Nothing in this repository should be read as saying the owner personally reviewed a specific result unless they add that themselves.

**What the owner should understand and review before relying on this work:**
- **The trust boundaries and residual risks** in [docs/security.md](docs/security.md), especially that grounding checks claims against quotes, not quotes against reality.
- **Cost settings.** The model prices in `config.py` and `.env.example` come from published price lists as of 2026-10-28 and will drift. The cost caps are only as good as those numbers.
- **The evaluation.** It is small, it was used while developing the prompts, and it is scored by a lexical heuristic. See [docs/evaluation.md](docs/evaluation.md) before quoting its numbers.
- **The code paths that decide what reaches users:**
  - `grounding.py`: evidence validation, claim checks, confidence.
  - `orchestrator.py`: the run loop and stop conditions.
  - `urls.py`: URL safety.
- **The repository license.** None has been chosen, and that decision belongs to the owner.

## Targeted improvement session

**Tool:** Claude Code in a cloud session (claude.ai/code), Claude Fable 5.1 model, on 2026-10-28, starting from `main` at `a7ec4d0`, on the branch `feature/evidence-quality`. The report is [docs/improvements.md](docs/improvements.md).

**What it did:**
- Wrote a frozen acceptance set (`tests/test_acceptance.py`) with independently authored expectations and ran it against the unchanged code first, so every defect below has a recorded "before".
- Changed the planning contract so compound criteria are listed in parts, made coverage per entity, made eligibility conjunctive per entity, tightened alias matching, and rebuilt the confidence rubric on the evidence that surviving claims cite.
- Made code-detected conflicts quote both sides and flag themselves for review; shortened comparison headers in the UI.
- Reproduced and fixed finalization under storage failure, made stream-slot release idempotent, and stopped exception text from reaching logs unless `LOG_CONTENT` is on.
- Added the offline source-dependency drill (`predixion deps`, an API endpoint, and a drawer section) with tests showing it makes no provider calls.
- Ran the fixture evaluation, the backend, frontend and browser suites, and a small live check within a $1 cap; results and their limits are in `docs/improvements.md`.
- Updated the documentation that had gone stale (test counts, the removed branch, Groq evaluation claims) and this file.

**What was not done:** no model change, no new provider, no change to the resource limits, and no human review. The held-out questions in `evals/heldout.md` were written before tuning; their results, where run, are reported as held-out only if no change was made because of them.

## Deployment session

**Tool:** Claude Code in a cloud session (claude.ai/code), Claude Fable 5.1 model, on 2026-10-29, starting from `main` after the improvement pass, on the branch `feature/cloud-run-deploy` (merged as pull request #10). This entry is written from the commit history and [docs/deployment.md](docs/deployment.md), because that session did not update this file itself.

**What it did (from the commits):**
- Added visitor access for token-mode servers (`PUBLIC_ACCESS`, `X-Visitor-Id`, owner keys derived from a hash of the id) and live-run admission limits (`LIVE_RUNS_PER_DAY`, `LIVE_RUNS_PER_USER_PER_HOUR`, 429 with `Retry-After`), with tests.
- Kept the daily live-run count in a ledger file that fails closed, and mounted a Cloud Storage volume for it on Cloud Run.
- Wrote `deploy/deploy.sh` and `deploy/cloudbuild.yaml`, which build one commit from `git archive` and deploy it by image digest with Secret Manager references.
- Deployed the service `predixion-ai` in `asia-south1` of the existing project `quantfolio-511108`, as a separate service with its own service accounts, and verified it with scripted checks against the public URL (its table is in `docs/deployment.md`). It reported about $0.06 of provider spend and no change to the existing QuantFolio service.
- Documented the architecture, limits, costs, operations and caveats, and added README badges and the demo-video link.

**What was not checked by that session's own account:** nothing in the repository says a person reviewed the deployment; its evidence is the session's own verification table.

## Deployment verification session

**Tool:** Claude Code in a cloud session (claude.ai/code), Claude Fable 5.1 model, on 2026-10-29, starting from `main` at `04807e6`, on the branch `feature/deployment-verification`. The report is [docs/deployment-audit.md](docs/deployment-audit.md).

**What it did:**
- Re-ran lint, the backend tests (266 passed, 1 skipped), the fixture evaluation, the frontend build, Vitest and Playwright from a fresh container, and read the CI run for `04807e6`.
- Checked the public URL with fresh synthetic visitor ids: security headers, readiness, authentication without and with wrong credentials, visitor isolation across every run route, idempotency, deletion, CORS, fault-injection and oversized-body refusals, a fixture run with its SSE stream and exports, and the UI in Chromium at desktop and mobile widths. It started no live run and spent nothing on providers.
- Scanned the served bundle, the deployment commits and CI for key-shaped strings (none found in the places looked at).
- Compared the deployed commit with `main` (documentation-only drift) and read the visitor and ledger code against its tests (no defect found).
- Fixed stale documentation: the submission notes still described the deployment as an unmerged pull request, the demo script said the video did not exist and the project was not deployed, the README had no Windows instructions, and this file had no deployment entry.

**What it could not do:** the session had no Google Cloud credentials, so traffic routing, the revision and image digest, Secret Manager bindings, runtime IAM, logs and the QuantFolio comparison are marked blocked in the report, and the deployment session's table is cited as reported history. The demo video was confirmed to exist (title and author from YouTube's metadata), not watched.

## Runtime LLM use

**OpenAI model.** The application calls an OpenAI model through the Responses API with strict JSON-schema outputs.
- Default: `gpt-6.1-terra` at reasoning effort `low` (`RESEARCH_MODEL`, `RESEARCH_REASONING_EFFORT`).
- `gpt-6-luna` was evaluated as a lower-cost alternative; see [docs/evaluation.md](docs/evaluation.md).
- The model is used at fixed steps: plan, extract quoted evidence, propose follow-up searches, synthesize a cited draft, verify claims against their quotes, and repair once.
- The model has no tools. Application code runs the searches and page reads, validates every model output, rejects quotes that are not in the page text, removes unsupported claims, and computes coverage, status, and confidence.
- Requests set `store: false`.

**Groq (optional).** With `GROQ_API_KEY` set, the plan and follow-up steps run first on OpenAI's open-weight models `openai/gpt-oss-120b` and `openai/gpt-oss-20b`, hosted by Groq. Every step can fall back between OpenAI and Groq when a provider fails. The same strict schemas and code checks apply to every model. See the README's model routing section.

**Tavily** provides search and page extraction. It is a retrieval service, not an LLM. Its own answer generation is turned off (`include_answer: false`).

**Fixture mode** uses scripted model and search responses. Fixture runs, tests, and the fixture evaluation make no provider calls.

**Claude is not used at runtime.** The application does not call any Anthropic model.
