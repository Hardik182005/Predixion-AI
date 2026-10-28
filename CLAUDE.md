# CLAUDE.md

Project conventions and verified commands for working on Predixion AI.

## Layout

- `src/predixion/`: the backend package (FastAPI, orchestrator, tools, grounding, evals, CLI). Start with `orchestrator.py` for the run loop and `contracts.py` for every data shape.
- `src/predixion/fixtures/scenarios/*.json`: the offline fixture world used by tests, fixture mode, and the fixture eval.
- `tests/`: pytest. Everything is offline except `test_live.py`, which needs `PREDIXION_LIVE_TESTS=1` and real keys.
- `frontend/`: React 19 + Vite + TypeScript + Tailwind 4.
  - `src/lib/types.ts` mirrors `contracts.py` by hand. Update both together.
  - `e2e/` holds Playwright tests.
- `evals/results/`: committed eval outputs. `evals/results/scratch/` is gitignored.
- `docs/`: requirements traceability, security, evaluation, demo script, submission notes, and sample reports.

## Commands (all verified on 2026-10-28)

```bash
uv sync                                   # install backend deps from uv.lock
uv run ruff check . && uv run ruff format --check .
uv run pytest                             # ~8 s, offline
uv run predixion eval --mode fixture      # offline regression suite; exit 0 = all agent checks pass
uv run predixion ask "question" --mode fixture
uv run predixion serve                    # http://127.0.0.1:8000

cd frontend
npm ci
npm run build                             # tsc --noEmit + vite build
npm test                                  # Vitest
npm run e2e                               # Playwright; needs `npm run build` first; starts its own fixture-mode server
```

Live evaluation spends real money. Always pass a cap:

```bash
uv run predixion eval --mode live --max-spend 0.50 --scenario vector_db_comparison --save-reports evals/results/scratch/x
```

## Conventions

- **The model proposes; the code decides.** Model outputs are strict JSON schemas (`prompts.py`) validated by application code. Do not give the model tools or let model output choose URLs, budgets, or destinations.
- **One retry owner.** `reliability.call_with_retries` owns retries; SDK retries stay off (`max_retries=0`). Provider adapters classify errors and never retry on their own.
- **Fixed provider endpoints.** They are constants in `config.py`, never configuration.
- **Prompt changes.** Bump `PROMPT_VERSION` in `config.py` whenever prompt text changes, then rerun the fixture eval.
- **Grounded claims only.** Every claim must cite evidence IDs that exist in the run. Quotes must appear in the page text.
- **Logging.** Never log question or page text unless `settings.log_content` is set. Never log keys.
- **Untrusted text.** Frontend renders untrusted text as text only. Use `safeHttpUrl` for every link.
- **Style.** Backend lines are at most 130 characters (ruff). Frontend uses exact dependency versions in `package.json`.
- **Tests stay offline.** Use fixture providers or `httpx.MockTransport`, never real providers outside `test_live.py`.

## Secrets and git

- Keys live only in `.env` (gitignored). Never print, commit, or paste them into fixtures, logs, or docs.
- Do not commit `01_Claude_Code_Build_Prompt.md`, `02_Claude_Cloud_Audit_Prompt.md`, or the assignment PDF; they are listed in `.git/info/exclude`.
- Work on feature branches. Commit messages are plain and descriptive, without AI co-author trailers.
