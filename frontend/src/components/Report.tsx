import type { ReactNode } from "react";

import { formatCost, formatDate, formatDateTime, formatDuration, plural, STAGE_LABEL, STOP_REASON_TEXT } from "../lib/format";
import type { CheckedText, ResearchReport, Source } from "../lib/types";
import { CoverageBadge, ModeBadge, Notice, StatusBadge, VerdictBadge } from "./Badges";
import { Citations, EvidenceProvider } from "./EvidenceDrawer";

function Section({ id, title, children, aside }: { id: string; title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section aria-labelledby={id} className="border-t border-line pt-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={id} className="text-lg font-semibold">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Checked({ item }: { item: CheckedText }) {
  return (
    <>
      <span>{item.text}</span>{" "}
      <span className="inline-flex flex-wrap items-center gap-1.5 align-middle">
        <Citations ids={item.evidence_ids} />
        {item.verdict !== "supported" && <VerdictBadge verdict={item.verdict} />}
      </span>
      {item.disposition === "qualified" && item.note && <span className="mt-1 block text-sm text-muted">Qualified: {item.note}</span>}
    </>
  );
}

function StatusNotice({ report }: { report: ResearchReport }) {
  const reason = report.stop_reason ? STOP_REASON_TEXT[report.stop_reason] : null;
  const detail = report.stop_detail && report.stop_detail !== reason ? report.stop_detail : null;
  const body = (
    <>
      {reason}
      {detail && <span className="mt-1 block">{detail}</span>}
    </>
  );
  switch (report.status) {
    case "partial":
      return (
        <Notice tone="warning" title="Partial answer: some criteria lack verified evidence.">
          {body}
        </Notice>
      );
    case "insufficient_evidence":
      return (
        <Notice tone="warning" title="Not enough evidence to answer.">
          The sources found do not support a reliable answer, so the report does not guess. {body}
        </Notice>
      );
    case "failed":
      return (
        <Notice tone="error" role="alert" title="The research run failed.">
          {body}
        </Notice>
      );
    case "cancelled":
      return <Notice title="This run was cancelled.">Anything shown below was collected before it stopped.</Notice>;
    case "interrupted":
      return (
        <Notice tone="error" title="This run was interrupted.">
          {body}
        </Notice>
      );
    default:
      return null;
  }
}

function SourceRow({ source }: { source: Source }) {
  return (
    <li className="flex flex-col gap-0.5 py-2 sm:flex-row sm:items-baseline sm:gap-3">
      <span className="font-mono text-xs text-muted">{source.id}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{source.title || source.domain}</span>
        <span className="text-sm text-muted">
          {source.domain} · {source.kind.replaceAll("_", " ")}
          {source.published_at && ` · published ${formatDate(source.published_at)}`}
          {source.fixture && " · synthetic"}
        </span>
      </span>
    </li>
  );
}

export function Report({ report }: { report: ResearchReport }) {
  const criteria = new Map((report.plan?.criteria ?? []).map((c) => [c.id, c.description]));
  const findings = report.key_findings.filter((f) => f.disposition !== "removed");
  const read = report.sources.filter((s) => s.state === "read");
  const unused = report.sources.filter((s) => s.state !== "read");
  const included = report.entities.filter((e) => e.included);
  const excluded = report.entities.filter((e) => !e.included);
  const m = report.execution.metrics;
  const v = report.verification;
  const hasAnswer = report.short_answer.text.trim().length > 0 && report.short_answer.disposition !== "removed";

  return (
    <EvidenceProvider report={report}>
      <article aria-label="Research report" className="space-y-8">
        <header className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={report.status} />
            <ModeBadge mode={report.mode} />
            <span className="text-xs text-muted">
              {formatDateTime(report.created_at)} · {report.execution.model}
            </span>
          </div>
          <StatusNotice report={report} />
          {report.plan?.ambiguity_note && (
            <Notice title="How the question was interpreted">{report.plan.ambiguity_note}</Notice>
          )}
        </header>

        {hasAnswer && (
          <section aria-labelledby="answer-title">
            <h2 id="answer-title" className="eyebrow">
              Short answer
            </h2>
            <p className="mt-2 text-xl leading-relaxed">
              <Checked item={report.short_answer} />
            </p>
          </section>
        )}

        {findings.length > 0 && (
          <Section id="findings-title" title="Key findings">
            <ol className="space-y-3">
              {findings.map((f, i) => (
                <li key={f.claim_id ?? i} className="flex gap-3 leading-relaxed">
                  <span aria-hidden="true" className="mt-0.5 font-mono text-xs text-muted">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div className="min-w-0">
                    {f.kind !== "fact" && <span className="mr-2 text-xs font-medium text-muted uppercase">{f.kind}</span>}
                    <Checked item={f} />
                  </div>
                </li>
              ))}
            </ol>
          </Section>
        )}

        {report.comparison && report.comparison.rows.length > 0 && (
          <Section id="comparison-title" title="Comparison">
            <div className="overflow-x-auto rounded-xl border border-line" tabIndex={0} role="region" aria-labelledby="comparison-title">
              <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
                <thead className="bg-soft">
                  <tr>
                    <th scope="col" className="p-3 font-semibold">
                      Option
                    </th>
                    {report.comparison.criteria.map((id) => (
                      <th key={id} scope="col" className="p-3 font-semibold">
                        {criteria.get(id) ?? id}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.comparison.rows.map((row) => (
                    <tr key={row.entity} className="border-t border-line align-top">
                      <th scope="row" className="p-3 font-medium">
                        {row.entity}
                      </th>
                      {report.comparison!.criteria.map((id) => {
                        const cell = row.cells.find((c) => c.criterion_id === id);
                        return (
                          <td key={id} className="p-3">
                            {!cell || cell.unknown || cell.disposition === "removed" ? (
                              <span className="text-muted">No verified evidence</span>
                            ) : (
                              <Checked item={cell} />
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {report.entities.length > 0 && (
          <Section
            id="entities-title"
            title="Matching organizations"
            aside={
              <span className="text-sm text-muted">
                {plural(included.length, "match", "matches")}
                {report.plan?.target_entity_count ? ` (asked for up to ${report.plan.target_entity_count})` : ""}
              </span>
            }
          >
            {included.length === 0 && <p className="text-muted">No candidate had evidence for every required condition.</p>}
            <ul className="space-y-4">
              {included.map((e) => (
                <li key={e.name} className="card p-4">
                  <p className="font-semibold">{e.name}</p>
                  {e.summary && (
                    <p className="mt-1 text-sm leading-relaxed">
                      <Checked item={e.summary} />
                    </p>
                  )}
                  <ul className="mt-3 space-y-1.5 text-sm">
                    {e.eligibility.map((c) => (
                      <li key={c.criterion_id} className="flex flex-wrap items-baseline gap-x-2">
                        <span className="font-medium">{c.status === "met" ? "Meets" : c.status === "not_met" ? "Does not meet" : "Unknown"}:</span>
                        <span className="text-muted">{criteria.get(c.criterion_id) ?? c.criterion_id}</span>
                        <Citations ids={c.evidence_ids} />
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
            {excluded.length > 0 && (
              <details className="mt-4 text-sm">
                <summary className="cursor-pointer text-muted">Considered but excluded ({excluded.length})</summary>
                <ul className="mt-2 space-y-1 pl-4">
                  {excluded.map((e) => (
                    <li key={e.name}>
                      <span className="font-medium">{e.name}</span>: {e.exclusion_reason ?? "eligibility not established"}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </Section>
        )}

        {report.conflicts.length > 0 && (
          <Section id="conflicts-title" title="Sources disagree">
            <ul className="space-y-3">
              {report.conflicts.map((c, i) => (
                <li key={i} className="rounded-xl border-2 border-ink p-4 text-sm leading-relaxed">
                  <p>
                    {c.description} <Citations ids={c.evidence_ids} />
                  </p>
                  {c.resolution && <p className="mt-1 text-muted">How the report handles it: {c.resolution}</p>}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {report.unresolved_criteria.length > 0 && (
          <Notice tone="warning" title="Missing evidence">
            <p>No verified evidence was found for:</p>
            <ul className="mt-1 list-disc pl-5">
              {report.unresolved_criteria.map((id) => (
                <li key={id}>{criteria.get(id) ?? id}</li>
              ))}
            </ul>
          </Notice>
        )}

        {report.coverage.length > 0 && (
          <Section id="coverage-title" title="Criteria coverage">
            <ul className="divide-y divide-line rounded-xl border border-line">
              {report.coverage.map((c) => (
                <li key={c.criterion_id} className="flex flex-col gap-1 p-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                  <div className="min-w-0 text-sm">
                    <p>
                      {c.description}
                      {!c.required && <span className="text-muted"> (optional)</span>}
                    </p>
                    {c.note && <p className="text-muted">{c.note}</p>}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-muted">
                      {plural(c.evidence_ids.length, "passage")}, {plural(c.independent_sources, "source")}
                    </span>
                    <CoverageBadge status={c.status} />
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section id="confidence-title" title="Confidence">
          <p className="text-sm leading-relaxed">
            <span className="font-semibold capitalize">{report.confidence.level}.</span> {report.confidence.explanation}
          </p>
          <p className="mt-2 text-sm text-muted">
            Verification: {v.supported} supported, {v.partially_supported} partly supported, {v.not_supported} not supported
            {v.unchecked > 0 && `, ${v.unchecked} not verified`} out of {plural(v.claims_checked, "claim")} checked.
            {v.removed_claims.length > 0 && ` ${plural(v.removed_claims.length, "unsupported claim")} removed.`}
          </p>
        </Section>

        {(report.limitations.length > 0 || report.assumptions.length > 0) && (
          <Section id="limits-title" title="Limitations and assumptions">
            <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
              {report.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
              {report.assumptions.map((a) => (
                <li key={a}>Assumption: {a}</li>
              ))}
            </ul>
          </Section>
        )}

        {report.next_steps.length > 0 && (
          <Section id="next-title" title="Next steps">
            <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
              {report.next_steps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </Section>
        )}

        <Section id="sources-title" title="Sources" aside={<span className="text-sm text-muted">{plural(read.length, "source")} read</span>}>
          {read.length === 0 ? (
            <p className="text-sm text-muted">No sources were read.</p>
          ) : (
            <ul className="divide-y divide-line">
              {read.map((s) => (
                <SourceRow key={s.id} source={s} />
              ))}
            </ul>
          )}
          {unused.length > 0 && (
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer text-muted">Found but not used ({unused.length})</summary>
              <ul className="mt-2 space-y-1">
                {unused.map((s) => (
                  <li key={s.id} className="break-words">
                    <span className="font-mono text-xs text-muted">{s.id}</span> {s.title || s.domain}{" "}
                    <span className="text-muted">
                      ({s.state}
                      {s.state_reason ? `: ${s.state_reason}` : ""})
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </Section>

        <details className="rounded-xl border border-line p-4 text-sm">
          <summary className="cursor-pointer font-medium">Execution details</summary>
          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-[auto_1fr]">
            <dt className="text-muted">Mode</dt>
            <dd>{report.execution.mode === "live" ? "Live (real web search and model calls)" : "Fixture (synthetic sources, scripted model)"}</dd>
            <dt className="text-muted">Model</dt>
            <dd>
              {report.execution.model}
              {report.execution.reasoning_effort && `, reasoning effort ${report.execution.reasoning_effort}`}
              {report.execution.sdk_version && `, SDK ${report.execution.sdk_version}`}
            </dd>
            <dt className="text-muted">Prompt version</dt>
            <dd>{report.execution.prompt_version}</dd>
            <dt className="text-muted">Duration</dt>
            <dd>{formatDuration(m.duration_ms)}</dd>
            <dt className="text-muted">Rounds</dt>
            <dd>{m.rounds}</dd>
            <dt className="text-muted">Searches · pages read</dt>
            <dd>
              {m.search_calls} · {m.pages_read}
            </dd>
            <dt className="text-muted">Model calls</dt>
            <dd>
              {m.model_calls} ({plural(m.model_attempts, "attempt")}, {plural(m.retries, "retry", "retries")}
              {m.model_fallbacks > 0 && `, ${plural(m.model_fallbacks, "fallback")}`})
            </dd>
            {Object.keys(m.models_used).length > 0 && (
              <>
                <dt className="text-muted">Models used</dt>
                <dd>
                  {Object.entries(m.models_used)
                    .map(([name, calls]) => `${name} (${plural(calls, "call")})`)
                    .join(", ")}
                </dd>
              </>
            )}
            <dt className="text-muted">Tokens</dt>
            <dd>
              {m.input_tokens.toLocaleString()} in · {m.output_tokens.toLocaleString()} out
            </dd>
            <dt className="text-muted">Estimated cost</dt>
            <dd>
              {formatCost(m.estimated_cost_usd, m.cost_uncertain)}
              {m.tavily_credits > 0 && ` (includes ${m.tavily_credits} search credits)`}
            </dd>
            <dt className="text-muted">Evidence</dt>
            <dd>
              {m.evidence_accepted} accepted, {m.evidence_rejected} rejected (quote not found in source, or invalid)
            </dd>
            {m.stage_timings.length > 0 && (
              <>
                <dt className="text-muted">Stage timings</dt>
                <dd>{m.stage_timings.map((t) => `${STAGE_LABEL[t.stage]} ${formatDuration(t.ms)}`).join(" · ")}</dd>
              </>
            )}
          </dl>
        </details>
      </article>
    </EvidenceProvider>
  );
}
