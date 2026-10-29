# Submission notes

## Links

| Item | Status |
|---|---|
| Repository | https://github.com/Hardik182005/Predixion-AI, branch `main`. The deployment work (pull request #10, `feature/cloud-run-deploy`) was merged into `main` on 2026-10-29. |
| Repository access | Private (`gh repo view` on 2026-10-29). Evaluators need collaborator access, or the owner needs to make it public. Visibility was checked, not changed. |
| Demo video | https://www.youtube.com/watch?v=WW-NYzoHdD0 |
| Hosted deployment | https://predixion-ai-8840249691.asia-south1.run.app on Google Cloud Run. Fixture runs are free; live runs are open to everyone within 20 a day in total and 3 per visitor an hour. History lasts only while the instance runs. See [deployment.md](deployment.md). |
| Evaluation | [evaluation.md](evaluation.md), raw results in [`evals/results/`](../evals/results/) |
| Sample reports | [samples/](samples/): live runs labeled with mode, date, model, and prompt version |
| Requirements traceability | [requirements.md](requirements.md) |
| Security model | [security.md](security.md) |
| AI usage disclosure | [AI_USAGE.md](../AI_USAGE.md) |
| Independent audit | [audit.md](audit.md): verification of every requirement, defects fixed, residual risks |
| Deployment verification | [deployment-audit.md](deployment-audit.md): independent check of the public URL, headers, access control, isolation, CI, docs; cloud-side checks marked blocked |
| Improvement pass | [improvements.md](improvements.md): evidence accounting, confidence, conflicts, finalization under storage failure, with before/after results |

## How to run it

The [README quick start](../README.md#quick-start) has the full steps. In short:

```bash
uv sync
cp .env.example .env
uv run predixion ask "Compare the top three open-source vector databases for a startup building RAG products." --mode fixture
```

Fixture mode needs no keys and makes no provider calls. Live mode needs `OPENAI_API_KEY` and `TAVILY_API_KEY` in `.env`.

## What was verified, and what was not

Verified locally on 2026-10-28 (Windows 11, Python 3.13, uv 0.10.11, Node.js 24):

- `uv run ruff check .` and `uv run ruff format --check .`: clean.
- `uv run pytest`: 216 passed, 1 skipped at the end of the build session; 219 after the audit fixes; 256 after the improvement pass ([improvements.md](improvements.md)). The skipped test is the opt-in live test.
- Frontend: `npm run build`, `npm test` (27 Vitest tests), and `npm run e2e` (7 Playwright tests, including axe accessibility scans).
- `uv run predixion eval --mode fixture`: 20 of 20 agent checks pass.
- Live evaluation with real OpenAI and Tavily calls; see [evaluation.md](evaluation.md).
- `pip-audit` and `npm audit --audit-level=high`: no known vulnerabilities.
- `docker build` succeeded with Docker 29.6.2. The container was then run in fixture mode:
  - `/healthz` and `/readyz` responded, the UI was served with its security headers, and Docker reported the container healthy.
  - It ran as a non-root user.
  - A research run through the API completed, and the Markdown and JSON exports worked.
  - `docker compose up` itself was not run; the compose file adds only the loopback port mapping, the `.env` file, and a volume.

Verified on GitHub on 2026-10-28: the CI run for commit `31b8e31` passed all four jobs (backend, frontend, secrets scan, Docker build) on `main` and on `feature/research-agent`. The CI run for `ca97a75` (the commit the audit started from) also passed all four jobs.

Verified by the independent audit session on 2026-10-28, from a fresh cloud container (Linux, Python 3.13.17, uv 0.11.32, Node.js 22.22.0): lint, 219 backend tests, the fixture evaluation (20 of 20 checks), the frontend build, 25 Vitest tests, 7 Playwright tests, `pip-audit`, and `npm audit`. After the sandbox network was opened for the provider hosts, the audit also ran the opt-in live test and three live evaluation runs (results in `evals/results/audit-live-*.md`). The Docker build was not possible in the sandbox; CI built it. See [audit.md](audit.md).

Verified by the deployment session on 2026-10-29, on `feature/cloud-run-deploy` (merged as pull request #10):
- Lint is clean.
- 266 backend tests pass and 1 is skipped.
- The fixture evaluation passes 20 of 20 checks.
- The frontend build, 29 Vitest tests, and 7 Playwright tests pass.
- The public URL passed checks of its security headers, access control, visitor isolation, fixture and live runs, and the live-run limits. The daily limit survived a restart.
- The logs contained no keys and no question text.
- QuantFolio was not changed.

The full list of checks is in [deployment.md](deployment.md#verification).

Verified by an independent review session on 2026-10-29, from a fresh cloud container without Google Cloud credentials, on `main` at `04807e6` (CI run 42 green): lint, 266 backend tests, the fixture evaluation, the frontend build, 29 Vitest and 7 Playwright tests, and the public URL's headers, access control, visitor isolation, fixture runs, exports and SSE, in Chromium at desktop and mobile widths. The deployed commit `034ae88` differs from `main` only in documentation. Traffic routing, Secret Manager bindings, runtime IAM, logs and QuantFolio isolation could not be checked without credentials and are marked blocked. No live run was started. See [deployment-audit.md](deployment-audit.md).

Not verified:

- **Owner review.** The owner has not reviewed the code, the evaluation, or the sample reports; see [AI_USAGE.md](../AI_USAGE.md). The live claims spot-checked in [evaluation.md](evaluation.md) were checked by the AI development assistant.

## Assignment checklist

Every item in the assignment brief, with where it is met. Checked against `main` at `236e030` on 2026-10-29.

| Brief item | Where | Status |
|---|---|---|
| Accept a question; plan; decide tools; gather and filter; structured final response; confidence, assumptions, limitations | `orchestrator.py` stages, `contracts.ResearchReport` | Done |
| Working agentic workflow with at least two tools | `tools.py`: `search_web` (Tavily Search), `read_sources` (Tavily Extract) | Done |
| Visible planning or orchestration | `plan` and `stage` events; UI plan panel and stage list; CLI stage log | Done |
| Structured final output with the seven fields (question, short answer, key findings, sources, confidence, limitations or assumptions, next steps) | `ResearchReport`; Markdown and JSON export | Done |
| Basic failure handling: timeouts, retries, malformed tool output, weak sources, hallucination risk, prompt injection, deterministic structure, logging and tracing, cost and latency | `reliability.py`, `llm.py`, `sources.py`, `urls.py`, `grounding.py`, `logs.py`; see [security.md](security.md) and [audit.md](audit.md) | Done |
| Short evaluation framework with at least five test queries, expected behavior, what worked and what did not | [evaluation.md](evaluation.md), 8 cases, `evals/results/`; plus [improvements.md](improvements.md) and `evals/heldout.md` | Done |
| README with setup, architecture, design decisions, known limitations, future improvements, and the seven README questions | [README](../README.md) | Done |
| Two or three sample outputs | [samples/](samples/): four live reports labelled by mode, date, model | Done |
| Demo video, 3–5 minutes, one happy path and one failure or edge case | [Video](https://www.youtube.com/watch?v=WW-NYzoHdD0), following [demo-script.md](demo-script.md) | Done |
| Source code repository accessible to evaluators | Private repository | **Pending: grant access or make public** |
| Stretch: citation grounding, evaluator or judge step, caching, async tool execution, guardrails for low-confidence answers, comparison with a non-agentic baseline | Quote and reference checks plus a verifier; `TTLCache`; asyncio with a semaphore; status and confidence rules, removal of unsupported claims; `evals.run_baseline` | Done |
| Stretch: memory for follow-up questions | Not implemented (optional); listed under future improvements | Not done |

## Before submitting

- [x] Record the demo video and add the link above.
- [x] Review and merge the deployment pull request (`feature/cloud-run-deploy`). Merged as pull request #10 on 2026-10-29; the service then ran `034ae88` from that branch, which differs from `main` only in documentation. It now runs `ab4ab22` from pull request #13, which adds the small-live-budget note; see [deployment.md](deployment.md).
- [ ] Review and merge the deployment verification pull request (`feature/deployment-verification`), or leave it unmerged if the audit record is not wanted on `main`.
- [ ] With Google Cloud access, reproduce the blocked checks in [deployment-audit.md](deployment-audit.md): traffic to `predixion-ai-00004-jbb`, secret references, runtime IAM, and QuantFolio's unchanged configuration.
- [ ] Set monthly usage limits in the OpenAI, Tavily, and Groq dashboards. The app caps live spend at about $6 a day, and a provider-side limit is a second line of defense.
- [x] Confirm the CI run on `main` passes for the audit commits. Run 23 (the same tree, before the audit commits were re-authored under the owner's identity) passed all four jobs (backend, frontend, secrets scan, Docker build) on 2026-10-28.
- [ ] Give evaluators access to the repository, or make it public.
- [x] Confirm the CI run on `main` passes on GitHub. Checked on 2026-10-28; see above.
- [x] Set `main` as the repository's default branch in GitHub settings. Done on 2026-10-28.
- [ ] Choose a license. None is included, and that decision belongs to the owner.
- [ ] Read [AI_USAGE.md](../AI_USAGE.md), the residual risks in [security.md](security.md), and the evaluation caveats in [evaluation.md](evaluation.md).
- [ ] Check the model prices in `config.py` and `.env.example` against current list prices; cost caps depend on them.
