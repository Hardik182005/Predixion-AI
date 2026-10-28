import type { CoverageStatus, RunStatus, Stage, StopReason, SupportVerdict } from "./types";

/** Only http(s) links are ever rendered as anchors; everything else is shown as text. */
export function safeHttpUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Researching",
  completed: "Completed",
  partial: "Partial answer",
  insufficient_evidence: "Not enough evidence",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

export const STOP_REASON_TEXT: Record<StopReason, string> = {
  criteria_satisfied: "Every required criterion has supporting evidence.",
  rounds_exhausted: "Stopped after the maximum number of research rounds.",
  diminishing_returns: "Stopped because further searching was finding nothing new.",
  no_actionable_gaps: "Stopped because the remaining gaps could not be searched for usefully.",
  deadline_reached: "Stopped at the time limit; the report uses the evidence collected so far.",
  budget_exhausted: "Stopped at the cost limit; the report uses the evidence collected so far.",
  page_budget_exhausted: "Stopped after reading the maximum number of pages.",
  no_relevant_sources: "No relevant sources were found.",
  provider_unavailable: "A search or model provider was unavailable.",
  provider_auth_error: "A provider rejected the server's credentials.",
  model_output_invalid: "The model's output could not be used after retries.",
  cancelled_by_user: "You cancelled this run.",
  process_interrupted: "The server stopped while this run was active.",
  internal_error: "An internal error stopped the run.",
};

export const STAGE_LABEL: Record<Stage, string> = {
  validate: "Check request",
  plan: "Plan",
  search: "Search",
  filter: "Filter sources",
  read: "Read pages",
  extract: "Extract evidence",
  assess: "Assess coverage",
  follow_up: "Follow up",
  synthesize: "Write answer",
  verify: "Verify claims",
  repair: "Repair claims",
  finalize: "Finalize",
};

export const STAGE_ORDER: Stage[] = [
  "validate",
  "plan",
  "search",
  "filter",
  "read",
  "extract",
  "assess",
  "follow_up",
  "synthesize",
  "verify",
  "repair",
  "finalize",
];

/** Stages that only run when needed; at the end they read "Not needed" rather than "Not reached". */
export const OPTIONAL_STAGES: ReadonlySet<Stage> = new Set(["follow_up", "repair"]);

export const VERDICT_LABEL: Record<SupportVerdict, string> = {
  supported: "Supported",
  partially_supported: "Partly supported",
  not_supported: "Not supported",
  unchecked: "Not verified",
};

export const COVERAGE_LABEL: Record<CoverageStatus, string> = {
  supported: "Supported",
  weak: "Weak evidence",
  conflicting: "Sources disagree",
  stale: "Possibly outdated",
  missing: "No evidence",
};

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

export function formatCost(usd: number, uncertain = false): string {
  const text = usd === 0 ? "$0" : usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(3)}`;
  return uncertain ? `about ${text}` : text;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "Unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "Unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
