# Sample reports

These are real reports from live runs on 2026-10-28. Each one was saved by `predixion eval --mode live --save-reports` and rendered with the app's Markdown exporter. They have not been edited. The header of each file gives the mode, date, model, and prompt version.

| Report | Question | Outcome | Prompt |
|---|---|---|---|
| [vector-db-comparison](vector-db-comparison.md) ([JSON](vector-db-comparison.json)) | Compare the top three open-source vector databases for a startup building RAG products. | Completed, High confidence, with a comparison table | `2026-10-28.3` |
| [hr-tech-discovery](hr-tech-discovery.md) ([JSON](hr-tech-discovery.json)) | Find five Indian B2B SaaS startups in HR tech and summarize their positioning. | Partial: 1 company confirmed, 6 candidates excluded with reasons | `2026-10-28.3` |
| [sqlite-contradictory](sqlite-contradictory.md) ([JSON](sqlite-contradictory.json)) | Is SQLite suitable for production web applications? | Partial, Low confidence, with conflicting sources reported | `2026-10-28.2` |

All three used `gpt-6.1-terra` at reasoning effort low, with Tavily for search and extraction.

[docs/evaluation.md](../evaluation.md#spot-check-of-live-claims) lists problems seen in these reports. They include overstated confidence on the vector report and generic conflict entries in the SQLite report. Sources, quotes, and dates are what the live web returned that day and may have changed since.
