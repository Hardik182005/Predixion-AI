# Submission notes

## Links

| Item | Status |
|---|---|
| Repository | https://github.com/Hardik182005/Predixion-AI, branch `main` (the only branch; the audit work was merged into it) |
| Repository access | Private (`gh repo view` on 2026-10-28). Evaluators need collaborator access, or the owner needs to make it public. Visibility was checked, not changed. |
| Demo video | **Pending.** Not recorded yet. Follow [demo-script.md](demo-script.md), then add the link here. |
| Hosted deployment | None. The app runs locally or in Docker; see the [README](../README.md#quick-start). |
| Evaluation | [evaluation.md](evaluation.md), raw results in [`evals/results/`](../evals/results/) |
| Sample reports | [samples/](samples/): live runs labeled with mode, date, model, and prompt version |
| Requirements traceability | [requirements.md](requirements.md) |
| Security model | [security.md](security.md) |
| AI usage disclosure | [AI_USAGE.md](../AI_USAGE.md) |
| Independent audit | [audit.md](audit.md): verification of every requirement, defects fixed, residual risks |

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
- `uv run pytest`: 216 passed, 1 skipped at the end of the build session; 219 passed, 1 skipped after the audit fixes (see below). The skipped test is the opt-in live test.
- Frontend: `npm run build`, `npm test` (25 Vitest tests), and `npm run e2e` (7 Playwright tests, including axe accessibility scans).
- `uv run predixion eval --mode fixture`: 20 of 20 agent checks pass.
- Live evaluation with real OpenAI and Tavily calls; see [evaluation.md](evaluation.md).
- `pip-audit` and `npm audit --audit-level=high`: no known vulnerabilities.
- `docker build` succeeded with Docker 29.6.2. The container was then run in fixture mode:
  - `/healthz` and `/readyz` responded, the UI was served with its security headers, and Docker reported the container healthy.
  - It ran as a non-root user.
  - A research run through the API completed, and the Markdown and JSON exports worked.
  - `docker compose up` itself was not run; the compose file adds only the loopback port mapping, the `.env` file, and a volume.

Verified on GitHub on 2026-10-28: the CI run for commit `31b8e31` passed all four jobs (backend, frontend, secrets scan, Docker build) on `main` and on `feature/research-agent`. The CI run for `ca97a75` (the commit the audit started from) also passed all four jobs.

Verified by the independent audit session on 2026-10-28, from a fresh cloud container (Linux, Python 3.13.17, uv 0.11.32, Node.js 22.22.0): lint, 219 backend tests, the fixture evaluation (20 of 20 checks), the frontend build, 25 Vitest tests, 7 Playwright tests, `pip-audit`, and `npm audit`. Live provider calls and the Docker build were blocked in that sandbox; see [audit.md](audit.md).

Not verified:

- **Owner review.** The owner has not reviewed the code, the evaluation, or the sample reports; see [AI_USAGE.md](../AI_USAGE.md). The live claims spot-checked in [evaluation.md](evaluation.md) were checked by the AI development assistant.

## Before submitting

- [ ] Record the demo video and add the link above.
- [x] Confirm the CI run on `main` passes for the audit commits. Run 23 (the same tree, before the audit commits were re-authored under the owner's identity) passed all four jobs (backend, frontend, secrets scan, Docker build) on 2026-10-28.
- [ ] Give evaluators access to the repository, or make it public.
- [x] Confirm the CI run on `main` passes on GitHub. Checked on 2026-10-28; see above.
- [x] Set `main` as the repository's default branch in GitHub settings. Done on 2026-10-28.
- [ ] Choose a license. None is included, and that decision belongs to the owner.
- [ ] Read [AI_USAGE.md](../AI_USAGE.md), the residual risks in [security.md](security.md), and the evaluation caveats in [evaluation.md](evaluation.md).
- [ ] Check the model prices in `config.py` and `.env.example` against current list prices; cost caps depend on them.
