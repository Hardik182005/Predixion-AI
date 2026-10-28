# Targeted improvement pass

A focused quality and reliability pass after the build and the independent audit. It changes how evidence is accounted for, how confidence is computed, how conflicts are explained, how follow-up research targets gaps, and what happens when storage fails at the end of a run. It does not rebuild the application, change the model, add a provider, or raise any resource limit.

| | |
|---|---|
| Date | 2026-10-28 |
| Session | Claude Code (claude.ai/code), Claude Fable 5.1, working on `feature/evidence-quality` |
| Starting commit | `a7ec4d0` on `main` (clean tree; CI run 26 green: backend, frontend, secrets, Docker) |
| Final tested code commit | `363844d` |
| Documentation-only commits after it | the commits that add this file, the live result files, and the documentation updates (listed in the pull request) |
| Live API spend in this pass | $0.42 estimated: $0.20 for the two after-change evaluation runs and $0.22 for the three held-out runs; cap $1 |

Method: a frozen acceptance set was written first and run against the unchanged code (`tests/test_acceptance.py`; the baseline outcomes are in the tables below), three held-out questions were written before any change (`evals/heldout.md`), and every behavior change has a regression test whose expected values were authored independently of the code.

## Confirmed defects and fixes

Severity and confidence are the reviewer's labels. "Baseline" is the behavior at `a7ec4d0`, reproduced by the acceptance probe before the change.

### 1. A compound criterion counted as supported with one part missing — medium, high confidence

- **Baseline.** The planner wrote "Verify an open-source core and identify its license" as one criterion; evidence that Milvus is open source made it `supported` and the run `completed`. Seen in the committed vector-database sample.
- **Fix.** The plan contract has a `parts` list per criterion (prompt version `2026-10-28.4`); `normalize_plan` turns a criterion with two or more parts into one criterion per part, each with `group` set to the parent, within the existing bound of 8 criteria. Coverage, follow-up, and the comparison table then treat each part on its own. A plan whose criteria are all optional is no longer satisfiable by no evidence: `required_satisfied([])` is False and such plans are normalized to all-required.
- **After.** Same input: two criteria, `K1 supported`, `K2 missing`, not completed.
- **Tests.** `test_compound_criterion_is_split_and_blocks_completion_until_every_part_has_evidence`, `test_parts_stay_within_the_plan_bound_and_a_single_part_is_not_split`, `test_a_plan_with_no_required_criterion_cannot_be_satisfied_by_nothing`.
- **Limit.** The split depends on the planner listing the parts. The prompt asks for it; a bundled criterion without parts is still judged as one.

### 2. One fresh source masked stale evidence for other entities — medium, high confidence

- **Baseline.** A comparison dimension with `needs_freshness` and three entities, where only one entity had a dated-recent source, was `supported`.
- **Fix.** Freshness is judged per entity for dimension criteria; the coverage carries `stale_entities` and the note names them ("No source dated within 365 days for: B, C").
- **Tests.** `test_freshness_is_judged_per_entity_in_a_comparison`, `test_one_entity_cannot_satisfy_another_entitys_dimension`.

### 3. An entity stayed included when a required eligibility check was simply omitted — medium, high confidence

- **Baseline.** `finalize_draft` excluded an entity only when a listed check was not met. An entity whose synthesis output omitted one eligibility criterion altogether stayed `included`.
- **Fix.** Eligibility is conjunctive per entity across every eligibility criterion in the plan: a missing check excludes the entity with the reason "Eligibility not established for: K2". Coverage notes for discovery name the entities each eligibility criterion is not established for, which is what the follow-up step needs to verify them.
- **Tests.** `test_entity_with_an_omitted_eligibility_check_is_not_included`, `test_discovery_eligibility_names_the_unverified_entities`.

### 4. Alias matching conflated different names — low, high confidence

- **Baseline.** `canonical_entity` matched on substrings of at least four characters: "Kekatech" became "Keka", "Milvus Lite" became "Milvus".
- **Fix.** Names match only when equal after normalization (case, punctuation, trailing legal-form words such as "Pvt. Ltd." or "Inc"). "Zoho People" is kept distinct from "Zoho"; the model is told to use the names on the entity list, and different names keep their own provenance.
- **Test.** `test_entity_aliases_match_conservatively`.

### 5. Confidence counted evidence that no claim used — medium, high confidence

- **Baseline.** `assess_confidence` counted independent domains and first-party share over every accepted evidence item. Adding two uncited sources moved a report from Medium to High. High required three domains, so one authoritative documentation page could never establish a narrow documented fact, and more than half first-party evidence blocked High even for a company's own headquarters.
- **Fix.** The rubric is built from the evidence cited by claims that survived verification (short answer, findings, comparison cells, entity assertions). Copies count once (content hash or duplicate link). A removed short answer, a material share of removed claims, an unresolved conflict, stale required criteria, or a comparative criterion without independent cited evidence rules out High. High needs two independent cited sites, or one high-suitability source when every required criterion is a narrow, non-comparative, question-level fact. First-party evidence is penalized only where it is the wrong kind of evidence. The rubric is documented in `docs/evaluation.md`; it shows no probabilities.
- **After.** Uncited sources: level unchanged, cited domains stay 2. Single authoritative source for a documented fact: High. Vendor-only comparative evidence across several sites: not High.
- **Tests.** `test_uncited_sources_cannot_raise_confidence`, `test_a_copy_of_a_cited_source_is_not_corroboration`, `test_removing_the_only_support_for_a_required_claim_cannot_improve_the_outcome`, `test_an_unresolved_conflict_prevents_high`, `test_one_authoritative_source_can_establish_a_narrow_documented_fact`, `test_vendor_only_comparative_evidence_prevents_high_even_with_several_sites`, `test_a_removed_short_answer_caps_confidence`.
- **Effect on existing fixtures.** Two scenarios (`hr_tech_india`, `vector_databases`) moved from Medium to High because the blanket first-party penalty is gone; their comparative criteria have independent evidence and their company facts come from company pages. The two test expectations were updated with that reasoning. The fixture evaluation's checks are unchanged (20 of 20).
- **Compatibility.** `ConfidenceAssessment.factors` is a free-form dictionary, so saved reports load unchanged. Historical results in `evals/results/` were produced by the earlier rubric and are not restated.

### 6. Conflicts said only "Sources disagree on K2" — low, high confidence

- **Fix.** Code-detected conflicts (opposite-polarity evidence about the same entity and criterion) now quote each side's claim with its evidence id, site, and date, name the criterion, and are flagged `review_needed`: the code checks that both sides address the same entity and criterion, not the same version or workload, so the UI labels them "Possible conflict, needs review" and says the report takes no side. Model-described conflicts keep their resolution text. Facts that differ without opposite polarity (two versions, two benchmarks) are not conflicts.
- **Tests.** `test_code_detected_conflicts_quote_both_sides_and_ask_for_review`, `test_facts_that_differ_without_opposite_polarity_are_not_a_conflict`.
- **UI.** Comparison headers show a short label with the full criterion text as a tooltip and for screen readers (`shortCriterion`, Vitest).

### 7. Finalization raised on storage failure and left the run stuck — high, high confidence

- **Baseline.** `RunManager._finish` called `save_report` before any cleanup. With `save_report` raising, the task ended with an exception, the done-callback called `_finish` again and raised again, the run stayed in `_active` (so it kept counting against capacity), subscribers were never told the run was over, and the stored status stayed `running`.
- **Fix.** `_finish` is idempotent and never raises. Storage failures are logged by category and location; the run is released from memory, every subscriber gets a terminal event whose data carries `persisted: false` and whose message says the report could not be saved, the status is set to `failed` with that error when the status write still works, and when nothing durable can be written the next start marks the run `interrupted` (existing `mark_interrupted`), which never restarts paid research. The report event is emitted only when the report was saved. A subscriber whose queue raises is dropped without affecting the others. The UI shows "The run finished, but its report could not be saved on the server" when it sees `persisted: false`.
- **Tests.** `test_report_save_failure_releases_the_run_and_reports_it_honestly` (also checks the next run is admitted), `test_persistent_storage_failure_is_recovered_as_interrupted_on_restart`, `test_event_persistence_failure_during_finalization_does_not_lose_the_report`, `test_finalization_is_idempotent_and_cancel_after_the_end_is_harmless`, `test_a_broken_subscriber_does_not_block_the_others`.
- **Not done.** Events, status, and report are still three separate SQLite writes, not one transaction; a crash between them is recovered by `mark_interrupted`, which is the documented guarantee. No owner-scoped fallback store was added; the database being unavailable is reported, not hidden.

### 8. Stream slots and error logs — low

- **Stream slot.** The audit's suspected leak (client disconnects before the response body starts) was not reproduced; the mid-stream disconnect path releases correctly. The slot is now an object whose `release()` is idempotent, called from both the body's `finally` and the response's background task, so the never-started path is covered without double release. Tests: `test_stream_slot_is_released_exactly_once`, `test_stream_slot_is_released_when_the_client_disconnects_mid_stream`.
- **Logs.** `logger.exception` wrote the exception text, which for a validation error included the offending value (reproduced with a synthetic sensitive value). Unexpected errors are now logged with `error` (type name) and `where` (innermost application frame) and no text unless `LOG_CONTENT=true`. Tests: `test_unexpected_exception_text_is_logged_only_with_log_content` (both settings), `test_error_location_names_the_application_frame`.

### 9. Follow-up did not search for the gap that mattered — medium, high confidence (trace evidence)

- **Trace.** In the audit's live vector run, the licensing criterion stayed `missing` because the follow-up step chose to read benchmark candidates (the prompt said to prefer reading candidates) although no candidate addressed licensing; no search was ever made for it. In the HR-tech sample, both follow-up queries returned listicles and all three round-2 slots went to round-1 aggregator pages; no per-entity verification page was read.
- **Fix.** (a) The follow-up prompt distinguishes verification (entity plus missing condition, prefer the entity's own site) from discovery, and says a `missing` gap with no candidate needs a search. (b) `_cover_untargeted_gaps` adds a rule-based search for any required `missing` criterion that no action targets, within the existing query cap and without near-repeats. (c) Round-2 page slots go first to the best new hit of each gap query (`_best_per_query`), then by rank, under the existing per-domain cap. (d) Coverage notes name the entities a criterion is missing for, so both the model and the rule-based query can target them.
- **Tests.** `test_a_required_missing_gap_gets_a_search_when_the_model_only_reads_other_candidates`, `test_follow_up_page_slots_are_spread_across_gap_queries`.
- **Live effect.** See the next section: the licensing criterion was reached in the after-change vector run; the HR-tech run read two per-entity profile pages in round 2 but still could not establish Indian incorporation from them.

## Before and after on controlled cases

Acceptance probe outcomes (same inputs, deterministic, no providers):

| Case | Baseline `a7ec4d0` | After `363844d` |
|---|---|---|
| Compound criterion (open-source core + license), evidence for one part | 1 criterion, `supported`, completion possible | 2 criteria, `supported` + `missing`, not complete |
| Three entities, one fresh source | `supported` | `stale`, "for: B, C" |
| Discovery entity with one eligibility check omitted | included | excluded, "not established for: K2" |
| Vendor-only comparative claim | `weak` | `weak` (unchanged) |
| Code-detected conflict text | "Sources disagree on K1 about SQLite." | both claims quoted with ids, sites, dates; `review_needed` |
| Two versions, same polarity | no conflict | no conflict (unchanged) |
| Confidence: add two uncited sources | Medium → High | unchanged, cited domains 2 → 2 |
| Confidence: one authoritative documentation source, narrow fact | Low | High |
| Confidence: unresolved conflict | Medium (not High) | Medium (unchanged) |
| Plan with no required criterion, zero evidence | satisfied | not satisfied |
| Alias "Kekatech" with known "Keka" | conflated | distinct |
| `save_report` raises at the end | exception, run stuck in memory, clients never told | released, terminal event `persisted: false`, status failed, next run admitted |
| Validation error with a sensitive value, `LOG_CONTENT=false` | value in the log | type and location only |

Fixture evaluation (offline, scripted model): agent 20/20 checks, 34/35 claims, 16/27 criteria before and after. Full suites after the change: 256 backend tests passed (1 opt-in live test skipped), 27 Vitest, 7 Playwright, ruff clean, `npm run build` clean.

## Live results

Single runs, live web, `gpt-6.1-terra` at reasoning effort low, Groq routing on (`plan` and `follow_up` on `openai/gpt-oss-120b`), 2 rounds, 8 pages, 2026-10-28. Costs are the app's list-price estimates. Plans differ between runs, so these are end-to-end comparisons of different plans, not fixed-plan comparisons; one run each proves nothing about rates.

| Question | Before (audit run, prompt `.3`, commit `5e37466`) | After (prompt `.4`, commit `363844d`) |
|---|---|---|
| Vector databases (`vector_db_comparison`) | `partial`, Low, 12/12 claims verified, 1/5 criteria supported, licensing `missing` (never searched), 3-row table, 52 s, $0.072, 3 searches | `partial`, Low, 21/21 claims verified, 1/5 criteria supported but every weak criterion names the entities it lacks, licensing `supported` after a round-2 search, 3-row table, two model-described conflicts (star counts; Qdrant hybrid retrieval), 72 s, $0.107, 5 searches |
| HR-tech discovery (`hr_tech_discovery`) | build-session sample, prompt `.3`: `partial`, Medium, 1 of 5 confirmed, 7 candidates, 87 s, $0.089 | `partial`, Low, 0 of 7 confirmed; every candidate excluded with the condition it lacks ("Indian incorporation is not confirmed"), round 2 read two per-entity profile pages, 61 s, $0.093 |

Sources: [`evals/results/improve-live-after.md`](../evals/results/improve-live-after.md); the "before" runs are in `evals/results/audit-live-smoke.md` and `docs/samples/hr-tech-discovery.md`.

What the live runs show and do not show:
- The untargeted-gap search worked as intended on the vector question (licensing was searched and established).
- The HR-tech answer became more conservative, not more complete. The Groq-planned criteria were stricter than the build session's (incorporation in India, startup status with an age and ownership test), the two profile pages read in round 2 did not state incorporation, and Low is the honest label for a report that confirms nothing. Reduced overconfidence is the intended direction; the completeness bottleneck is now the planner's criteria and what aggregator profiles state, not slot allocation.
- The planner on the vector question named seven candidates although the question asked for three, so three "not established for" entities are planner inventions the coverage then reports honestly. That is a planner-quality issue with the Groq-hosted model, not a coverage defect, and it is left as is.
- Latency is still dominated by model calls (extract 24 s + 10 s, synthesize 22 s of 72 s in the vector run); search and page reads together took under 5 s. No code-path optimization was attempted, because none would move the total.

## Held-out questions

Written before any change in `evals/heldout.md` and not inspected during iteration. One live run each, same configuration as above. No change in this pass was made because of them.

| Id | Expected behavior (from `evals/heldout.md`) | Outcome | Met? |
|---|---|---|---|
| `H1` Airflow, Prefect, Dagster: Python 3.13 support and licenses | Separate criteria for support and license; row-level "not found"; documentation sources; no ranking | `partial`, Low, 6/6 claims verified, 34 s, $0.076. Two separate criteria (Python 3.13 eligibility; license dimension). The planner chose entity discovery rather than a comparison and added its own "latest stable release" condition, so no tool was confirmed and no table was produced; the answer states per tool what was and was not established (Airflow 3.2.0 docs list 3.13; Prefect announced it; Dagster not established) with documentation and vendor sources and no ranking. | Mostly: criteria and sources as required; no comparison table because of the planner's task-type choice |
| `H2` Three European invoice-financing fintechs for small businesses | Include only entities with all conditions met; name the missing condition for the rest; no padding | `partial`, Low, 20/20 claims verified, 58 s, $0.092. Factris included with all four eligibility checks met and cited; MatchPlace and Malcom Finance excluded with "European headquarters … and 2026 operating status are not established". Fewer than three, no padding. | Yes |
| `H3` Is Redis still open source? | Dated sources, licence changes over time, versions distinguished, conflict or version-dependent answer | `completed`, High, 5/5 claims verified, 28 s, $0.049. Version-dependent answer (BSD-3 up to 7.2; RSALv2, SSPLv1 or AGPLv3 from Redis 8), dated sources (2026-03, 2026-10), one conflict between an undated client-library license file and a version-specific account, resolved in favor of the dated, version-specific source. The answer says it cannot settle OSI approval of AGPLv3 from the reviewed evidence. | Yes. Note: High here means every kept claim is supported by cited, dated, independent sources; the answer itself is explicit that the question is not conclusively settled, and the sources are medium-tier sites rather than the Redis project's own pages. |

Reports: `evals/results/heldout/H1.json`, `H2.json`, `H3.json` (same configuration as the runs above; commit `363844d`, prompt `2026-10-28.4`). Nothing was changed after seeing these outcomes; they remain held-out.

## Optional source-dependency drill: implemented

`src/predixion/dependencies.py`, `predixion deps REPORT.json --source S3`, `GET /api/runs/{id}/dependencies?source=S3` (owner-scoped), and a "Source dependencies" section in the evidence drawer. It works on a deep copy of the report's claim → evidence → source graph, removes one source or its recorded duplicate family (same content hash or duplicate link), and lists claims that lose every citation, claims that keep some, and criteria to reassess. It is labelled "Source-dependency analysis, not a new fact check" and makes no model, search, or extraction calls (`test_no_provider_calls_are_made` patches the provider clients to fail). Tests cover single and multiple sources, compound claims, duplicate families, unknown ids, owner scoping, and non-mutation.

## Regressions and tradeoffs

- Confidence is more conservative on reports whose answer rests on uncited or vendor-only evidence, and less conservative on reports whose facts correctly come from a company's own pages. Both are intended.
- A compound criterion now takes two of the eight criterion slots; `normalize_plan` truncates at eight.
- Coverage notes are longer (they name entities). The Markdown export still uses full criterion text as table headers.
- `_cover_untargeted_gaps` can add a search the model chose not to make; it is bounded by the existing query cap and near-repeat filter.

## Unverified hypotheses and blocked checks

- The never-started stream-body leak was not reproduced; the idempotent release covers it by construction.
- Transactional consistency of status, report, and events was not implemented; recovery relies on `mark_interrupted`.
- The lexical scorer's false-positive rate is not measured.
- Docker was not available in the session; CI builds the image.
- The full live suite was not re-run under the new rubric; live claims here rest on single runs.

## Checks run

`uv sync --frozen`; `uv run ruff check . && uv run ruff format --check .`; `uv run pytest` (256 passed, 1 skipped); `uv run predixion eval --mode fixture` (20/20); `npm ci`, `npm run build`, `npm test` (27), Playwright (7, with the container's preinstalled Chromium); two live evaluation runs and three held-out live runs; CI on the final commits is linked from the pull request.
