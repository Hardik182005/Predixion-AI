# Demo script (3–5 minutes)

This script covers one live happy path and one failure case. The recording has not been made yet. Once it is uploaded, add the link to [submission.md](submission.md).

## Before recording

```bash
uv sync
cd frontend && npm ci && npm run build && cd ..
```

In `.env`:
- Set `OPENAI_API_KEY` and `TAVILY_API_KEY`.
- Set `PREDIXION_MODE=live`, `SERVE_FRONTEND_DIR=frontend/dist` and `ENABLE_FAULT_INJECTION=true`. The last one enables the "simulate a failure" control. Leave it off anywhere except a local demo.

Then:
- Run `uv run predixion serve` and open http://127.0.0.1:8000.
- Do one warm-up live run so the timing is familiar. A live run took 25–90 seconds in the evaluation.
- Close other tabs. Zoom the browser to about 110% so the text is readable in the video.

If live keys are unavailable, every step except the timing works in fixture mode. Say on camera that it is fixture mode.

## Script

### 0:00–0:30 · What it is

On the landing page:

> "Predixion AI answers research questions that need several sources. It searches, reads the most useful pages, and shows exactly which passage supports each claim. When the evidence is thin, it says so instead of guessing."

Point at the tagline and the evidence-card illustration. Click **Start research**.

### 0:30–2:30 · Happy path (live)

1. Choose the sample "Compare the top three open-source vector databases for a startup building RAG products." Confirm **Live web research** is selected. Click **Start research**.
2. While it runs, narrate the progress panel:
   - **Plan:** the criteria it will check (for example licensing, scale, hosting, ecosystem) and the first queries. *"This plan comes from the model, but the code decides how many searches and pages it gets."*
   - **Stages:** move as real events arrive. *"There are no fake percentage bars; each step is a server event."*
   - **Coverage:** after assessment, some criteria may show as missing. If the run does a follow-up round, point that out: *"It searched again only for what was missing."*
3. When the report appears:
   - Read the short answer and two key findings.
   - Show the comparison table.
   - Click a citation such as **E3**. The drawer shows the exact quoted passage, the source, its date, and any caveats. Press Escape; focus returns to the citation.
   - Point at **Confidence** and its reasons, and at **Limitations** and **Next steps**.
   - Open **Execution details**: searches, pages read, model calls, tokens, estimated cost (a few cents), and stage timings.
4. Click **Export Markdown** to show the report can be taken away.

### 2:30–3:45 · Failure case

1. Click **New research**. Use "Is SQLite suitable for production web applications?" or any question.
2. Open **Advanced: simulate a failure (testing)** and choose **Search provider is down**. Start the run.
3. Narrate as it fails:
   > "The search tool fails every time. The retry logic tries a bounded number of times and then stops. It does not invent an answer."
4. Show the result:
   - Status **Failed** with the explanation.
   - No key findings.
   - Confidence **Low**.
   - The **Retry** button.
5. Optional, if there is time. Run "What does QuantumLeap Vector Engine 9 from Hyperion DB cost?" without a fault. It is a product that does not exist. The run ends **Not enough evidence**, and the report says it found nothing reliable rather than making up a price.

### 3:45–4:30 · How it is checked

Show the terminal or the repository:
- `uv run pytest` passes 219 backend tests offline.
- `uv run predixion eval --mode fixture` runs the 8-scenario regression suite at no cost.
- `evals/results/live-gpt-6.1-terra.md` holds the live comparison with a one-pass baseline. The agent covered about twice as many criteria; it was about 8× slower and 2.3× more expensive.

Close with:

> "The model proposes; the code decides. Every claim in the report either has a quoted source behind it or it is removed."

## Things to avoid saying

- That the answers are guaranteed correct. Verification checks claims against their quotes, not the quotes against reality.
- That this is production-ready or deployed. It runs locally; [README](../README.md) lists what remains before public use.
- That the owner manually reviewed the evaluation, unless they have done so before recording.
