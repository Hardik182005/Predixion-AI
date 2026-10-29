# Deployment verification

An independent review of the Cloud Run deployment, run on 2026-10-29 in a fresh Claude Code cloud session that had no Google Cloud credentials. It verified what could be observed from the public URL, the repository, CI, and a real browser, and marks everything that needed cloud access as blocked. The deployment session's own checks are in [deployment.md](deployment.md#verification); this document does not repeat them as facts. Where this review says "reported", it means the claim comes from that session or from commit history and was not re-verified here.

This document is a record. Later reviews should add a dated section rather than edit the evidence below.

## Review of 2026-10-29

### What was reviewed

| Item | Value | How it was established |
|---|---|---|
| Repository `main` | `04807e6` (merge of PR #11) | `git log` at 18:05 UTC |
| Review branch | `feature/deployment-verification` | Created by this session for the changes below |
| Deployed commit | `034ae88` | Reported in [deployment.md](deployment.md) (the image is built from `git archive` of that commit). Not verified from the image: no cloud access, and a label would not be proof anyway. |
| Deployed revision | `predixion-ai-00004-jbb` | Reported; not verified |
| Image digest | `sha256:a19121d9…` | Reported; not verified |
| Service, region, project | `predixion-ai`, `asia-south1`, `quantfolio-511108` (number `8840249691`) | Project number matches the public URL's host; the rest is reported |
| Public URL | https://predixion-ai-8840249691.asia-south1.run.app | Opened over HTTPS; see below |
| Runtime account | `predixion-run@quantfolio-511108.iam.gserviceaccount.com` | Named in `deploy/deploy.sh`; the live binding is reported, not verified |
| CI on `main` | Run 42 for `04807e6`: backend, frontend, secrets scan and Docker build all passed | GitHub Actions API, 18:07 UTC |
| Drift between deployed commit and `main` | Documentation only | `git diff --stat 034ae88 04807e6` touches `README.md`, `docs/deployment.md`, `docs/security.md`, `docs/submission.md`. No change under `src/`, `frontend/`, `Dockerfile` or `deploy/`. So the deployed image is expected to match `main`'s application code, on the assumption that it was built from `034ae88` as reported. |

Timestamps below are UTC on 2026-10-29. Every request used fresh random visitor ids and synthetic questions. No request went to any other service in the project.

### Results

PASS means observed here. BLOCKED means it needed access this session did not have. REPORTED means the deployment session recorded it and this session could not check it.

#### Availability and rendering

| Check | Result | Evidence (18:19 UTC unless noted) |
|---|---|---|
| `GET /` over HTTPS | PASS | 200, `text/html`, the built frontend |
| `GET /readyz` | PASS | 200 `{"status":"ready"}` |
| `GET /healthz` | PASS (documented caveat) | 404 from Google's front end, as [deployment.md](deployment.md#known-caveats) says. `/readyz` is the usable probe. |
| `http://` redirect to `https://` | BLOCKED | The sandbox proxy would not resolve the plain-HTTP host. The `run.app` domain is HTTPS-only by Google's design; reported as 302 by the deployment session. |
| `/api/docs`, `/api/openapi.json` | PASS | 404; no API explorer is exposed |
| Desktop rendering (1280×800, Chromium) | PASS | White background, tagline heading, no horizontal overflow, no console errors |
| Mobile rendering (390×844) | PASS | Same page, no overflow |
| Sample research | PASS | Opening the sample shows the "Fixture demo" label and the synthetic-data notice; findings, plan, coverage and a comparison table render |
| Evidence drawer | PASS | Opening a citation shows the passage, the source, the caveats, and the "Source dependencies" section with its "not a new fact check" note |
| Exports | PASS | Markdown download works in the browser; `GET …/export?format=markdown` is labelled "Fixture demo" and the JSON export's `run_id` matches |
| SSE | PASS | A fixture run streamed stage events and ended with a terminal event carrying `persisted: true`. One aborted SSE request appeared in the console when the page navigated after a download; it is the browser cancelling the stream, not an error. |
| Live mode in the UI for a visitor | PASS | The "Live web research" choice is enabled without a token; no fault-injection control is shown |

#### Authentication and isolation (public URL, synthetic visitors)

| Check | Result | Evidence |
|---|---|---|
| No token and no visitor id | PASS | 401 on `POST /api/runs` and `GET /api/runs` |
| Wrong bearer token with a valid visitor id | PASS | 401; no fallback to visitor access |
| Malformed visitor id (too short) | PASS | 401 |
| Visitor `GET /api/config` | PASS | `live_available: true`, `fault_injection: false`, cost cap `0.3`; no key-shaped strings in the body |
| Fault injection from a visitor | PASS | 403 `fault_injection_disabled` |
| Oversized body | PASS | 413 |
| Seed URL pointing at the metadata address | PASS | 422 `unsafe_url` |
| Fixture run as visitor A | PASS | Completed; export, events and the dependencies endpoint return 200 for A |
| Visitor B opens A's run, events, export, cancel, delete | PASS | 404 on every route; B's run list is empty |
| Malformed run id | PASS | 404 |
| Idempotency | PASS | The same key and body returns the same run; the same key with a different body returns 409 `idempotency_conflict` |
| Owner deletion | PASS | A's `DELETE` returns 204, then the run is 404 for A as well |
| CORS preflight from a foreign origin | PASS | 400 and no `Access-Control-Allow-Origin` for that origin |
| Cookies | PASS (not applicable) | No cookie is set; write actions are authorised by a header, so CSRF via cookies does not apply |
| Live-run quota (429) and `Retry-After` | REPORTED | Not re-tested, to avoid spending the shared daily allowance of 20 live runs on a review; `tests/test_api.py::test_live_run_limits` covers the logic offline and passed here |
| Paid live run | REPORTED | No live run was started by this review (spend $0). The deployment session recorded one run at about $0.06. |

#### Security headers (observed on `/`, `/readyz`, and `/api/config`)

| Header | Result | Value |
|---|---|---|
| `Content-Security-Policy` | PASS | `default-src 'self'; script-src 'self'; … object-src 'none'; frame-ancestors 'none'; base-uri 'none'` |
| `Strict-Transport-Security` | PASS | `max-age=31536000` |
| `X-Content-Type-Options` | PASS | `nosniff` |
| `X-Frame-Options` | PASS | `DENY` |
| `Referrer-Policy` | PASS | `no-referrer` |
| `Permissions-Policy` | PASS | Present, denying camera, microphone and geolocation |
| `Cache-Control` on API responses | PASS | `no-store` |
| Assets and SSE under the CSP | PASS | The built bundle, styles and the event stream all loaded in Chromium with the policy applied |

#### Secrets

| Check | Result | Evidence |
|---|---|---|
| Browser bundle and source maps | PASS | No `.map` files are served; no `sk-`, `tvly-`, `gsk_` or bearer-shaped strings in the served JavaScript |
| Git history since `3d20b0d` | PASS | No key-shaped strings in the diff of the deployment commits |
| `.env`, build prompts | PASS | Not tracked (`.gitignore` and `.git/info/exclude`) |
| CI logs | PASS | The secrets-scan job (gitleaks) passed on run 42 |
| Secret Manager references, runtime IAM, Cloud Run logs, image layers | BLOCKED | Needs `gcloud` with a credentialed account. Reported in [deployment.md](deployment.md): four secrets passed as references, no key material in 113 log entries. |

A passing scan shows only that the patterns it looked for were absent in the places it looked.

#### Cloud configuration and isolation

| Check | Result |
|---|---|
| Traffic routes to `predixion-ai-00004-jbb` | BLOCKED (no cloud credentials). Reported: 100% to that revision. |
| Port, request timeout, concurrency, instance limits | PASS in code, BLOCKED on the service. `deploy/deploy.sh` sets port 8000 (the container's port), a 300 s request timeout above the 120 s run deadline so an event stream can follow a whole run, concurrency 60, and at most 1 instance (runs and SQLite are per instance). Whether the live service carries those values could not be read without credentials; reported as deployed with them. |
| Account identity and permissions | BLOCKED. `gcloud auth list` shows no credentialed account in this session. |
| QuantFolio untouched, compared with the baseline | BLOCKED. Reported: `quantfolio-api-00001-445` serving 100%, generation 1, before and after. This review made no request to QuantFolio and changed nothing in the project. |
| Ledger durability across a restart | REPORTED, and covered offline by `test_daily_live_limit_survives_a_restart_through_the_ledger`. Not re-induced: a redeploy would disrupt the live service. |

#### Honest persistence

The README, [deployment.md](deployment.md) and [security.md](security.md) all say that runs are not durable, that history lasts only while the instance is up, that SQLite lives in instance memory, and that the only durable state is the live-run ledger on the Cloud Storage volume. That matches the code (`RunManager` holds asyncio tasks in the process; the store is a SQLite file under `/app/data`, which is not a mounted volume). PASS.

#### Local checks on `04807e6` (fresh container, Python 3.13, Node.js 22)

| Check | Result |
|---|---|
| `uv run ruff check .` and `ruff format --check .` | PASS |
| `uv run pytest` | PASS: 266 passed, 1 skipped (the opt-in live test) |
| `uv run predixion eval --mode fixture` | PASS: 20 of 20 |
| `npm run build` | PASS |
| `npm test` | PASS: 29 tests |
| `npm run e2e` (preinstalled Chromium) | PASS: 7 tests |
| `npm audit --audit-level=high` | PASS: 0 |

#### README, demo and submission

| Check | Result |
|---|---|
| Deployed URL in README | PASS: the "Live demo" badge and the "Try it" line point at the public URL, which opens |
| Demo link | PASS: README and `docs/submission.md` link exactly https://www.youtube.com/watch?v=WW-NYzoHdD0. The YouTube oEmbed endpoint returned the title "Predixion AI Demo \| Evidence-Based Research Agent" by Hardik Hinduja, so the video exists and is public. Playback, duration, and whether it shows the successful and the failure/edge-case workflows were not checked: the sandbox cannot play video. |
| CI badge | PASS with a caveat: the badge resolves for people with access; the repository is private, so an evaluator without access sees a broken image. Noted in the README. |
| Local setup | FAIL, fixed: the quick start was bash-only (`cp`, `&&` chains), although the owner develops on Windows. PowerShell equivalents were added. [deployment.md](deployment.md) already says `deploy/deploy.sh` needs Git Bash or another POSIX shell. |
| `docs/submission.md` | FAIL, fixed: it still said the deployment work was on `feature/cloud-run-deploy` awaiting review. That pull request (#10) was merged into `main` on 2026-10-29. |
| `docs/demo-script.md` | FAIL, fixed: three stale lines said the recording had not been made, that there were no per-user quotas, and that the project was not deployed. |
| `AI_USAGE.md` | FAIL, fixed: it had no entry for the deployment session. One was added from commit history and `docs/deployment.md`, and an entry for this review. |
| Repository access for evaluators | Human task. The repository is private. Visibility was not changed. |

### Code review of the deployment changes

The visitor-scoping and ledger code (`api.py::current_owner`, `runs.py::_admit_live`) was read against the tests. No defect was found. Points worth knowing, all already documented:

- A visitor id is a scope, not a credential. Anyone who has it can read that visitor's runs. The hourly per-visitor limit is fairness, not a spend bound; the daily ledger is the spend bound.
- Fixture runs are not counted. A flood of them can keep the single instance up and fill the run queue (3 running, 6 queued). There is no edge rate limiting.
- When the ledger cannot be read or written, live runs are refused with 503. That is the intended fail-closed behaviour, and it means a Cloud Storage outage turns off live research.

### Changes made by this review

All in pull request `feature/deployment-verification` → `main`, not merged by this session:

- This document.
- `README.md`: PowerShell quick start, a note on the CI badge and the private repository.
- `docs/submission.md`: deployment pull request recorded as merged; verification list updated.
- `docs/demo-script.md` and the PDF: stale lines corrected.
- `AI_USAGE.md`: deployment session and this review.

No application code changed, so the deployed revision does not need to be replaced for this review. Redeploying was not authorised and would not have been possible without credentials.

### Residual risks and remaining tasks

- Everything under BLOCKED above is unverified by an independent party: traffic routing, revision, image digest, Secret Manager bindings, runtime IAM, logs, Cloud Run timeouts, and QuantFolio isolation. A person with access can reproduce the deployment session's read-only checks with the commands in [deployment.md](deployment.md#operating-it).
- The repository is private. Evaluators need access or the repository needs to be public.
- Provider-side monthly spend limits (OpenAI, Tavily, Groq) are recommended as a second bound; the app's bound is 20 runs × $0.30 a day.
- The demo video's content was not reviewed here.
- No edge rate limiting; fixture-run floods are bounded only by the queue and the single instance.

### Reproducing the safe checks

Replace `URL` with the service URL. These make no provider calls and spend nothing.

```bash
curl -sI URL/ | grep -i -E "content-security|strict-transport|x-content-type|x-frame|referrer|permissions"
curl -s URL/readyz
curl -s -o /dev/null -w "%{http_code}\n" URL/api/runs                     # 401
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Visitor-Id: short" URL/api/runs   # 401
V=$(head -c 24 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=')
curl -s -H "X-Visitor-Id: $V" URL/api/config
curl -s -X POST -H "X-Visitor-Id: $V" -H "Content-Type: application/json" \
  -d '{"question":"Compare the top three open-source vector databases for a startup building RAG products.","mode":"fixture"}' URL/api/runs
```

Then, with the returned run id and a second random visitor id, `GET URL/api/runs/<id>` returns 200 for `$V` and 404 for the other.
