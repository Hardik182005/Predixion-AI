import { type FormEvent, useId, useState } from "react";

import type { FaultInjection, Mode, ResearchRequest, SampleQuestion, ServerConfig } from "../lib/types";

// Failure simulations the server accepts when fault injection is enabled. Labels say what the run will experience.
const FAULTS: { id: string; label: string; fault: FaultInjection }[] = [
  { id: "search_unavailable", label: "Search provider is down", fault: { search: "unavailable" } },
  { id: "search_rate_limited", label: "Search provider rate-limits every request", fault: { search: "rate_limited" } },
  { id: "search_empty", label: "Search returns no results", fault: { search: "empty" } },
  { id: "extract_partial", label: "Some pages fail to load", fault: { extract: "partial" } },
  { id: "extract_all_failed", label: "Every page fails to load", fault: { extract: "all_failed" } },
  { id: "model_malformed", label: "Model returns malformed output", fault: { model: "malformed" } },
  { id: "model_unavailable", label: "Model provider is down", fault: { model: "unavailable" } },
];

export function QuestionForm({
  config,
  samples,
  busy,
  error,
  initialQuestion = "",
  onSubmit,
  onRequestToken,
}: {
  config: ServerConfig | null;
  samples: SampleQuestion[];
  busy: boolean;
  error: string | null;
  initialQuestion?: string;
  onSubmit: (request: ResearchRequest) => void;
  onRequestToken?: () => void;
}) {
  const ids = useId();
  const [question, setQuestion] = useState(initialQuestion);
  const [mode, setMode] = useState<Mode | null>(null);
  const [fault, setFault] = useState("");
  const [touched, setTouched] = useState(false);

  const min = config?.limits.question_min_chars ?? 3;
  const max = config?.limits.question_max_chars ?? 2000;
  const liveAvailable = config?.live_available ?? false;
  const needsToken = liveAvailable && (config?.live_needs_token ?? false);
  const liveUsable = liveAvailable && !needsToken;
  const selectedMode: Mode = mode ?? (liveUsable ? (config?.default_mode ?? "fixture") : "fixture");
  const length = question.trim().length;
  const invalid = length < min ? `Enter a question of at least ${min} characters.` : length > max ? `Keep the question under ${max} characters.` : null;
  const shownError = (touched && invalid) || error;

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (invalid || busy) return;
    const chosen = FAULTS.find((f) => f.id === fault);
    onSubmit({ question: question.trim(), mode: selectedMode, ...(chosen ? { fault: chosen.fault } : {}) });
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5" aria-describedby={shownError ? `${ids}-error` : undefined}>
      <div>
        <label htmlFor={`${ids}-q`} className="text-sm font-medium">
          Research question
        </label>
        <textarea
          id={`${ids}-q`}
          name="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          maxLength={max + 200}
          placeholder="For example: Compare the top three open-source vector databases for a startup building RAG products."
          aria-invalid={touched && invalid ? true : undefined}
          aria-describedby={`${ids}-hint${shownError ? ` ${ids}-error` : ""}`}
          className="mt-2 block w-full resize-y rounded-xl border border-neutral-400 bg-white p-4 text-base leading-relaxed placeholder:text-neutral-500 focus:border-ink focus:outline-2 focus:outline-offset-2 focus:outline-ink"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
        />
        <p id={`${ids}-hint`} className="mt-1.5 flex justify-between gap-4 text-xs text-muted">
          <span>Ask one question. Ctrl+Enter starts the research.</span>
          <span aria-hidden="true">
            {length}/{max}
          </span>
        </p>
      </div>

      {samples.length > 0 && (
        <div>
          <p className="text-sm font-medium" id={`${ids}-ex`}>
            Examples
          </p>
          <ul aria-labelledby={`${ids}-ex`} className="mt-2 flex flex-wrap gap-2">
            {samples.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className="rounded-full border border-line px-3 py-1.5 text-left text-sm text-neutral-700 hover:border-ink hover:text-ink"
                  onClick={() => {
                    setQuestion(s.question);
                    setTouched(false);
                  }}
                >
                  {s.question}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <fieldset>
        <legend className="text-sm font-medium">Mode</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <label
            className={`flex gap-3 rounded-xl border p-3 ${selectedMode === "live" ? "border-ink" : "border-line"} ${liveUsable ? "cursor-pointer" : "opacity-60"}`}
          >
            <input
              type="radio"
              name="mode"
              value="live"
              checked={selectedMode === "live"}
              disabled={!liveUsable}
              onChange={() => setMode("live")}
              className="mt-1 accent-ink"
              aria-describedby={`${ids}-live`}
            />
            <span>
              <span className="block text-sm font-medium">Live web research</span>
              <span id={`${ids}-live`} className="block text-xs text-muted">
                {needsToken
                  ? "Needs an access token: live research calls paid providers, so this server limits it to invited users."
                  : liveAvailable
                    ? `Searches the web and calls ${config?.model ?? "the model"}. Up to ${Math.round((config?.limits.run_deadline_s ?? 0) / 60)} minutes and $${config?.limits.max_cost_usd_per_run ?? 0} per run.`
                    : "Unavailable: the server has no search or model credentials configured."}
              </span>
            </span>
          </label>
          <label className={`flex cursor-pointer gap-3 rounded-xl border p-3 ${selectedMode === "fixture" ? "border-ink" : "border-line"}`}>
            <input
              type="radio"
              name="mode"
              value="fixture"
              checked={selectedMode === "fixture"}
              onChange={() => setMode("fixture")}
              className="mt-1 accent-ink"
              aria-describedby={`${ids}-fixture`}
            />
            <span>
              <span className="block text-sm font-medium">Fixture demo</span>
              <span id={`${ids}-fixture`} className="block text-xs text-muted">
                Synthetic sources and a scripted model. Free and offline; results are not real research.
              </span>
            </span>
          </label>
        </div>
        {needsToken && onRequestToken && (
          <button type="button" className="mt-2 text-sm font-medium underline" onClick={onRequestToken}>
            Enter an access token
          </button>
        )}
      </fieldset>

      {config?.fault_injection && (
        <details className="rounded-xl border border-dashed border-neutral-400 p-3 text-sm">
          <summary className="cursor-pointer font-medium">Advanced: simulate a failure (testing)</summary>
          <label htmlFor={`${ids}-fault`} className="mt-3 block text-muted">
            Inject a provider failure to see how the run degrades.
          </label>
          <select
            id={`${ids}-fault`}
            value={fault}
            onChange={(e) => setFault(e.target.value)}
            className="mt-2 w-full rounded-lg border border-neutral-400 bg-white p-2"
          >
            <option value="">No failure</option>
            {FAULTS.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </select>
        </details>
      )}

      {shownError && (
        <p id={`${ids}-error`} role="alert" className="text-sm font-medium text-danger">
          {shownError}
        </p>
      )}

      <button type="submit" className="btn-primary w-full sm:w-auto" disabled={busy} aria-disabled={busy}>
        {busy ? "Starting…" : "Start research"}
      </button>
    </form>
  );
}
