// Mirrors src/predixion/contracts.py. Only the fields the UI reads are listed.

export type Mode = "live" | "fixture";

export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "partial"
  | "insufficient_evidence"
  | "failed"
  | "cancelled"
  | "interrupted";

export const TERMINAL_STATUSES: ReadonlySet<RunStatus> = new Set([
  "completed",
  "partial",
  "insufficient_evidence",
  "failed",
  "cancelled",
  "interrupted",
]);

export type StopReason =
  | "criteria_satisfied"
  | "rounds_exhausted"
  | "diminishing_returns"
  | "no_actionable_gaps"
  | "deadline_reached"
  | "budget_exhausted"
  | "page_budget_exhausted"
  | "no_relevant_sources"
  | "provider_unavailable"
  | "provider_auth_error"
  | "model_output_invalid"
  | "cancelled_by_user"
  | "process_interrupted"
  | "internal_error";

export type Stage =
  | "validate"
  | "plan"
  | "search"
  | "filter"
  | "read"
  | "extract"
  | "assess"
  | "follow_up"
  | "synthesize"
  | "verify"
  | "repair"
  | "finalize";

export type EventType = "status" | "stage" | "plan" | "tool" | "coverage" | "warning" | "report" | "error";

export type CoverageStatus = "supported" | "weak" | "conflicting" | "stale" | "missing";
export type SupportVerdict = "supported" | "partially_supported" | "not_supported" | "unchecked";
export type ClaimDisposition = "kept" | "qualified" | "removed";
export type CriterionKind = "dimension" | "eligibility" | "general";

export interface FaultInjection {
  search?: "none" | "unavailable" | "rate_limited" | "auth" | "empty";
  extract?: "none" | "unavailable" | "partial" | "all_failed";
  model?: "none" | "unavailable" | "malformed" | "refusal";
}

export interface ResearchRequest {
  question: string;
  mode?: Mode;
  seed_urls?: string[];
  max_rounds?: number;
  fault?: FaultInjection;
}

export interface Criterion {
  id: string;
  description: string;
  kind: CriterionKind;
  required: boolean;
  /** Parent requirement when the planner split a compound criterion into parts. */
  group?: string | null;
}

export interface PlannedQuery {
  id: string;
  text: string;
  purpose: string;
}

export interface ResearchPlan {
  objective: string;
  task_type: "comparison" | "entity_discovery" | "pros_cons" | "explainer";
  interpretation: string;
  assumptions: string[];
  ambiguity_note: string | null;
  target_entity_count: number | null;
  candidate_entities: string[];
  criteria: Criterion[];
  queries: PlannedQuery[];
}

export interface Source {
  id: string;
  url: string;
  domain: string;
  title: string;
  kind: string;
  tier: "high" | "medium" | "low";
  state: "candidate" | "read" | "failed" | "filtered" | "duplicate";
  state_reason: string | null;
  retrieved_at: string | null;
  published_at: string | null;
  published_at_origin: "provider_estimate" | "page_text" | "unknown";
  injection_suspected: boolean;
  fixture: boolean;
}

export interface Evidence {
  id: string;
  source_id: string;
  quote: string;
  claim: string;
  criterion_ids: string[];
  entity: string | null;
  polarity: "supports" | "contradicts";
  first_party: boolean;
}

export interface CheckedText {
  claim_id: string | null;
  text: string;
  evidence_ids: string[];
  verdict: SupportVerdict;
  disposition: ClaimDisposition;
  note: string | null;
}

export interface Finding extends CheckedText {
  kind: "fact" | "interpretation" | "recommendation";
  criterion_ids: string[];
}

export interface ComparisonCell extends CheckedText {
  criterion_id: string;
  unknown: boolean;
}

export interface ComparisonTable {
  criteria: string[];
  rows: { entity: string; cells: ComparisonCell[] }[];
}

export interface EligibilityCheck extends CheckedText {
  criterion_id: string;
  status: "met" | "not_met" | "unknown";
}

export interface EntityResult {
  name: string;
  included: boolean;
  summary: CheckedText | null;
  eligibility: EligibilityCheck[];
  exclusion_reason: string | null;
}

export interface CriterionCoverage {
  criterion_id: string;
  description: string;
  kind: CriterionKind;
  required: boolean;
  status: CoverageStatus;
  evidence_ids: string[];
  independent_sources: number;
  note: string | null;
  missing_entities?: string[];
  stale_entities?: string[];
}

export interface Conflict {
  description: string;
  criterion_ids: string[];
  evidence_ids: string[];
  entity: string | null;
  resolution: string | null;
  /** Detected by code from opposite-polarity evidence; a possible conflict that needs a human read. */
  review_needed?: boolean;
}

export interface VerificationSummary {
  claims_checked: number;
  supported: number;
  partially_supported: number;
  not_supported: number;
  unchecked: number;
  invalid_references_removed: number;
  repair_attempted: boolean;
  removed_claims: string[];
  note: string | null;
}

export interface ExecutionMetrics {
  duration_ms: number | null;
  first_event_ms: number | null;
  stage_timings: { stage: Stage; ms: number }[];
  rounds: number;
  search_calls: number;
  pages_read: number;
  model_calls: number;
  model_attempts: number;
  retries: number;
  model_fallbacks: number;
  models_used: Record<string, number>;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  cost_uncertain: boolean;
  tavily_credits: number;
  sources_discovered: number;
  sources_filtered: number;
  evidence_accepted: number;
  evidence_rejected: number;
}

export interface ExecutionInfo {
  mode: Mode;
  model: string;
  sdk_version: string | null;
  prompt_version: string;
  reasoning_effort: string | null;
  limits: Record<string, number>;
  metrics: ExecutionMetrics;
}

export interface ResearchReport {
  run_id: string;
  question: string;
  status: RunStatus;
  stop_reason: StopReason | null;
  stop_detail: string | null;
  mode: Mode;
  short_answer: CheckedText;
  key_findings: Finding[];
  comparison: ComparisonTable | null;
  entities: EntityResult[];
  sources: Source[];
  evidence: Evidence[];
  coverage: CriterionCoverage[];
  unresolved_criteria: string[];
  conflicts: Conflict[];
  confidence: { level: "high" | "medium" | "low"; explanation: string };
  limitations: string[];
  assumptions: string[];
  next_steps: string[];
  plan: ResearchPlan | null;
  /** Every checked statement with its citations; used offline for source-dependency lookups. */
  claims?: Claim[];
  verification: VerificationSummary;
  execution: ExecutionInfo;
  created_at: string;
}

export interface Claim {
  id: string;
  location: "short_answer" | "finding" | "comparison_cell" | "entity" | "eligibility";
  kind: "fact" | "interpretation" | "recommendation";
  text: string;
  evidence_ids: string[];
  verdict: SupportVerdict;
}

export interface RunEvent {
  seq: number;
  ts: string;
  type: EventType;
  stage: Stage | null;
  message: string;
  data: Record<string, unknown> | null;
}

export interface RunSummary {
  run_id: string;
  status: RunStatus;
  question: string;
  mode: Mode;
  created_at: string;
  updated_at: string;
  stop_reason: StopReason | null;
}

export interface RunView extends RunSummary {
  report: ResearchReport | null;
  plan: ResearchPlan | null;
  last_event_seq: number;
  error: string | null;
}

export interface StartRunResponse {
  run_id: string;
  status: RunStatus;
  reused: boolean;
}

export interface ServerConfig {
  version: string;
  default_mode: Mode;
  live_available: boolean;
  /** The server lets this visitor run fixture mode only; live research needs an access token. */
  live_needs_token: boolean;
  model: string;
  auth_mode: "none" | "token";
  fault_injection: boolean;
  limits: {
    question_min_chars: number;
    question_max_chars: number;
    max_rounds: number;
    max_pages_per_run: number;
    run_deadline_s: number;
    max_cost_usd_per_run: number;
  };
}

export interface SampleQuestion {
  id: string;
  question: string;
}
