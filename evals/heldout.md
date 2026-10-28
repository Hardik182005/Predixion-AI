# Held-out questions

Written on 2026-10-28 before the targeted improvement pass changed any behavior. These questions were not used while tuning; their outcomes were not inspected during iteration. If a later change is tuned to one of them, that question must be relabelled development data here.

Each row states the behavior a correct report must show. These are behavioral criteria, not answer keys: a report that abstains honestly where the web lacks evidence satisfies the criteria.

| Id | Question | Expected behavior |
|---|---|---|
| `H1` | Which open-source workflow orchestration tools (Airflow, Prefect, Dagster) support Python 3.13, and under which licenses? | Comparison with one row per named tool. "Python 3.13 support" and "license" are separate criteria or parts; a row whose license is not found says so instead of counting the Python support as covering both. Licensing claims cite documentation or repository sources. No "best" ranking. |
| `H2` | Find three European fintech startups that offer invoice financing to small businesses. | Entity discovery. An entity is included only when European location, invoice-financing product, and small-business focus are each established for that same entity. Fewer than three with reasons is acceptable; padding is not. Exclusion reasons name the missing condition. |
| `H3` | Is Redis still open source? | Explainer with a freshness requirement. The answer must address the licence changes over time with dated sources, distinguish Redis the company from forks or the Redis project versions, and report a conflict or a version-dependent answer rather than a flat yes or no if sources differ by date. |

## How to run

```bash
uv run predixion ask "<question>" --mode live --json --out evals/results/scratch/heldout-H1.json
```

Live runs cost about $0.05–0.10 each. Record the model, routing, prompt version, date, and commit with each result.

## Results

None recorded yet.
