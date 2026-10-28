import { formatDateTime, OPTIONAL_STAGES, STAGE_LABEL, STAGE_ORDER } from "../lib/format";
import type { RunState } from "../lib/useRun";
import type { Stage } from "../lib/types";
import { CoverageBadge, Notice } from "./Badges";

type StageState = "done" | "current" | "pending" | "skipped" | "not_reached";

function stageState(stage: Stage, seen: Stage[], current: Stage | null, terminal: boolean): StageState {
  if (seen.includes(stage)) return !terminal && stage === current ? "current" : "done";
  if (!terminal) return "pending";
  return OPTIONAL_STAGES.has(stage) ? "skipped" : "not_reached";
}

const STATE_TEXT: Record<StageState, string> = {
  done: "Done",
  current: "In progress",
  pending: "Waiting",
  skipped: "Not needed",
  not_reached: "Not reached",
};

function StageIcon({ state }: { state: StageState }) {
  if (state === "done") {
    return (
      <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4">
        <circle cx="8" cy="8" r="8" fill="currentColor" />
        <path d="M4.5 8.2l2.3 2.3 4.7-4.9" fill="none" stroke="#fff" strokeWidth="1.8" />
      </svg>
    );
  }
  if (state === "current") return <span aria-hidden="true" className="pulse-dot block size-4 rounded-full border-2 border-ink bg-white" />;
  return <span aria-hidden="true" className="block size-4 rounded-full border border-dashed border-neutral-400" />;
}

/** Live view of a run: stages, plan, coverage as it is assessed, and an activity log. No percentages: progress is not linear. */
export function RunProgress({ run }: { run: RunState & { terminal: boolean } }) {
  const { plan, coverage, stagesSeen, currentStage, terminal, connection, reconnectAttempt } = run;
  const coverageById = new Map(coverage.map((c) => [c.criterion_id, c]));
  const log = run.events.filter((e) => e.type === "tool" || e.type === "warning" || e.type === "error" || e.type === "stage").slice(-40).reverse();

  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_1fr]">
      <section aria-labelledby="stages-title" className="card p-5">
        <h2 id="stages-title" className="eyebrow">
          Stages
        </h2>
        <p className="sr-only" aria-live="polite">
          {terminal ? "Research finished." : currentStage ? `Current stage: ${STAGE_LABEL[currentStage]}` : "Starting research."}
        </p>
        <ol className="mt-3 space-y-2.5">
          {STAGE_ORDER.map((stage) => {
            const state = stageState(stage, stagesSeen, currentStage, terminal);
            return (
              <li
                key={stage}
                className={`flex items-center gap-3 text-sm ${state === "pending" || state === "skipped" || state === "not_reached" ? "text-muted" : ""}`}
                aria-current={state === "current" ? "step" : undefined}
              >
                <StageIcon state={state} />
                <span className={state === "current" ? "font-semibold" : ""}>{STAGE_LABEL[stage]}</span>
                <span className="sr-only">: {STATE_TEXT[state]}</span>
                {(state === "skipped" || state === "not_reached") && (
                  <span aria-hidden="true" className="ml-auto text-xs">
                    {STATE_TEXT[state]}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
        {(stagesSeen.includes("follow_up") || !terminal) && (
          <p className="mt-4 text-xs text-muted">Search, read and extract can repeat when follow-up rounds run.</p>
        )}
      </section>

      <div className="min-w-0 space-y-6">
        {connection === "reconnecting" && (
          <Notice tone="warning" role="status" title="Connection lost. Reconnecting…">
            Attempt {reconnectAttempt}. The run continues on the server; updates will resume where they left off.
          </Notice>
        )}

        <section aria-labelledby="plan-title" className="card p-5">
          <h2 id="plan-title" className="eyebrow">
            Plan
          </h2>
          {!plan ? (
            <p className="mt-3 text-sm text-muted">{terminal ? "No plan was produced." : "Planning the research…"}</p>
          ) : (
            <div className="mt-3 space-y-4">
              <p className="leading-relaxed">{plan.interpretation}</p>
              {plan.ambiguity_note && <Notice title="Ambiguous question">{plan.ambiguity_note}</Notice>}
              <div>
                <h3 className="text-sm font-medium">What the answer must establish</h3>
                <ul className="mt-2 divide-y divide-line rounded-xl border border-line">
                  {plan.criteria.map((c) => {
                    const cov = coverageById.get(c.id);
                    return (
                      <li key={c.id} className="flex flex-col gap-1 p-3 text-sm sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                        <span>
                          {c.description}
                          {!c.required && <span className="text-muted"> (optional)</span>}
                        </span>
                        {cov ? (
                          <CoverageBadge status={cov.status} />
                        ) : (
                          <span className="shrink-0 text-xs text-muted">{terminal ? "Not assessed" : "Not assessed yet"}</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
              {plan.queries.length > 0 && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-muted">First-round searches ({plan.queries.length})</summary>
                  <ul className="mt-2 list-disc space-y-1 pl-5">
                    {plan.queries.map((q) => (
                      <li key={q.id}>{q.text}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </section>

        <section aria-labelledby="activity-title" className="card p-5">
          <h2 id="activity-title" className="eyebrow">
            Activity
          </h2>
          {log.length === 0 ? (
            <p className="mt-3 text-sm text-muted">Waiting for the first update…</p>
          ) : (
            <ol className="mt-3 max-h-72 space-y-1.5 overflow-y-auto pr-2 text-sm" tabIndex={0} aria-label="Activity log, newest first">
              {log.map((e) => (
                <li key={e.seq} className={`flex gap-3 ${e.type === "error" ? "text-danger" : ""}`}>
                  <time dateTime={e.ts} className="shrink-0 font-mono text-xs leading-5 text-muted" title={formatDateTime(e.ts)}>
                    {new Date(e.ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                  </time>
                  <span className={`min-w-0 break-words ${e.type === "stage" ? "font-medium" : ""}`}>
                    {e.type === "warning" && <span className="font-medium">Warning: </span>}
                    {e.message}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}
