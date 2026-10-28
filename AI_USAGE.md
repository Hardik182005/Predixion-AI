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
- `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`: 191 passed, 1 skipped. The skipped test is the opt-in live test.
- `npm run build` (TypeScript check plus production build), `npm test` (24 Vitest tests), and `npm run e2e` (7 Playwright tests, including axe accessibility scans).
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

## Runtime LLM use

**OpenAI model.** The application calls an OpenAI model through the Responses API with strict JSON-schema outputs.
- Default: `gpt-6.1-terra` at reasoning effort `low` (`RESEARCH_MODEL`, `RESEARCH_REASONING_EFFORT`).
- `gpt-6-luna` was evaluated as a lower-cost alternative; see [docs/evaluation.md](docs/evaluation.md).
- The model is used at fixed steps: plan, extract quoted evidence, propose follow-up searches, synthesize a cited draft, verify claims against their quotes, and repair once.
- The model has no tools. Application code runs the searches and page reads, validates every model output, rejects quotes that are not in the page text, removes unsupported claims, and computes coverage, status, and confidence.
- Requests set `store: false`.

**Tavily** provides search and page extraction. It is a retrieval service, not an LLM. Its own answer generation is turned off (`include_answer: false`).

**Fixture mode** uses scripted model and search responses. Fixture runs, tests, and the fixture evaluation make no provider calls.

**Claude is not used at runtime.** The application does not call any Anthropic model.
