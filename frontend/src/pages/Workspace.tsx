import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { ModeBadge, Notice, StatusBadge } from "../components/Badges";
import { QuestionForm } from "../components/QuestionForm";
import { Report } from "../components/Report";
import { RunProgress } from "../components/RunProgress";
import { ApiError, api, downloadExport, newIdempotencyKey, setToken } from "../lib/api";
import { formatDateTime, STOP_REASON_TEXT } from "../lib/format";
import { Link, navigate } from "../lib/router";
import type { ResearchRequest, RunSummary, SampleQuestion, ServerConfig } from "../lib/types";
import { useRun } from "../lib/useRun";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Try again.";
}

function TokenPrompt({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!value.trim()) return;
    setToken(value.trim());
    onSaved();
  }
  return (
    <form onSubmit={submit} className="card mx-auto max-w-md space-y-4 p-6">
      <h1 className="text-xl font-semibold">Access token required</h1>
      <p className="text-sm text-muted">
        This server requires an API token. It is kept in this browser tab only and sent with each request.
      </p>
      <div>
        <label htmlFor="token" className="text-sm font-medium">
          API token
        </label>
        <input
          id="token"
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="mt-2 block w-full rounded-lg border border-neutral-400 p-2.5"
        />
      </div>
      <button type="submit" className="btn-primary">
        Continue
      </button>
    </form>
  );
}

/** Starts runs with an idempotency key that is reused if the same request is retried after a network error. */
function useStartRun() {
  const pending = useRef<{ body: string; key: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(async (request: ResearchRequest) => {
    const body = JSON.stringify(request);
    if (pending.current?.body !== body) pending.current = { body, key: newIdempotencyKey() };
    setBusy(true);
    setError(null);
    try {
      const response = await api.startRun(request, pending.current.key);
      pending.current = null;
      navigate(`/research/${response.run_id}`, { replace: false });
      return true;
    } catch (err) {
      setError(errorText(err));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  return { start, busy, error };
}

function RecentRuns({ refreshKey }: { refreshKey: number }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  useEffect(() => {
    let active = true;
    api
      .listRuns(8)
      .then((r) => active && setRuns(r))
      .catch(() => active && setRuns([]));
    return () => {
      active = false;
    };
  }, [refreshKey]);
  if (!runs || runs.length === 0) return null;
  return (
    <section aria-labelledby="recent-title" className="mt-12">
      <h2 id="recent-title" className="eyebrow">
        Recent runs
      </h2>
      <ul className="mt-3 divide-y divide-line rounded-xl border border-line">
        {runs.map((run) => (
          <li key={run.run_id}>
            <Link
              href={`/research/${run.run_id}`}
              className="flex flex-col gap-1 p-3 hover:bg-soft sm:flex-row sm:items-center sm:justify-between sm:gap-4"
            >
              <span className="min-w-0 truncate text-sm font-medium">{run.question}</span>
              <span className="flex shrink-0 items-center gap-2 text-xs text-muted">
                <StatusBadge status={run.status} />
                {run.mode === "fixture" ? "Fixture" : "Live"} · {formatDateTime(run.created_at)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NewResearch({ config, samples }: { config: ServerConfig | null; samples: SampleQuestion[] }) {
  const { start, busy, error } = useStartRun();
  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-14">
      <h1 className="text-3xl font-semibold tracking-tight">New research</h1>
      <p className="mt-2 text-muted">
        Ask a question that needs several sources. The report cites a quoted passage for every claim and says what it could not find.
      </p>
      <div className="mt-8">
        <QuestionForm config={config} samples={samples} busy={busy} error={error} onSubmit={start} />
      </div>
      <RecentRuns refreshKey={0} />
    </div>
  );
}

/** `/research?sample=<id>`: starts a fixture run of a sample question once, then shows it. */
function SampleStarter({ sampleId, samples }: { sampleId: string; samples: SampleQuestion[] | null }) {
  const { start, error } = useStartRun();
  const started = useRef<string | null>(null);
  useEffect(() => {
    if (!samples || started.current === sampleId) return;
    const sample = samples.find((s) => s.id === sampleId);
    if (!sample) return;
    started.current = sampleId;
    void start({ question: sample.question, mode: "fixture" });
  }, [sampleId, samples, start]);

  const unknown = samples !== null && !samples.some((s) => s.id === sampleId);
  return (
    <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
      {unknown || error ? (
        <Notice tone="error" role="alert" title="Could not start the sample.">
          {unknown ? "That sample does not exist." : error} <Link href="/research" className="underline">Start a new research run</Link>.
        </Notice>
      ) : (
        <p role="status" className="text-muted">
          Starting the sample run…
        </p>
      )}
    </div>
  );
}

function RunPage({ runId, config }: { runId: string; config: ServerConfig | null }) {
  const run = useRun(runId);
  const { start, busy: retrying, error: retryError } = useStartRun();
  const [actionError, setActionError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const { view, terminal, error } = run;
  const report = view?.report ?? null;
  const status = run.status ?? view?.status ?? null;

  useEffect(() => heading.current?.focus(), [runId]);

  async function cancel() {
    setCancelling(true);
    setActionError(null);
    try {
      await api.cancelRun(runId);
    } catch (err) {
      setActionError(errorText(err));
    } finally {
      setCancelling(false);
    }
  }

  async function exportAs(format: "md" | "json") {
    setActionError(null);
    try {
      await downloadExport(runId, format);
    } catch (err) {
      setActionError(errorText(err));
    }
  }

  if (error && !view) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
        <h1 ref={heading} tabIndex={-1} className="text-2xl font-semibold outline-none">
          {error.status === 404 ? "Run not found" : "Could not load this run"}
        </h1>
        <div className="mt-4">
          <Notice tone="error" role="alert" title={error.status === 404 ? "This run does not exist or was deleted." : error.message}>
            {error.status !== 404 && (
              <button type="button" className="btn-secondary mt-3" onClick={run.reload}>
                Try again
              </button>
            )}
          </Notice>
        </div>
        <Link href="/research" className="btn-primary mt-6">
          New research
        </Link>
      </div>
    );
  }

  const canRetry = terminal && status !== "completed" && view;
  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <div className="flex flex-col gap-4 border-b border-line pb-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {status && <StatusBadge status={status} />}
            {view && <ModeBadge mode={view.mode} />}
          </div>
          <h1 ref={heading} tabIndex={-1} className="mt-3 text-2xl leading-snug font-semibold tracking-tight break-words outline-none">
            {view?.question ?? "Loading run…"}
          </h1>
          {view && <p className="mt-1 text-sm text-muted">Started {formatDateTime(view.created_at)}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {view && !terminal && (
            <button type="button" className="btn-secondary" onClick={cancel} disabled={cancelling}>
              {cancelling ? "Cancelling…" : "Cancel"}
            </button>
          )}
          {canRetry && (
            <button
              type="button"
              className="btn-secondary"
              disabled={retrying}
              onClick={() => void start({ question: view.question, mode: view.mode })}
            >
              {retrying ? "Starting…" : "Retry"}
            </button>
          )}
          {report && (
            <>
              <button type="button" className="btn-secondary" onClick={() => void exportAs("md")}>
                Export Markdown
              </button>
              <button type="button" className="btn-secondary" onClick={() => void exportAs("json")}>
                Export JSON
              </button>
            </>
          )}
          <Link href="/research" className="btn-primary">
            New research
          </Link>
        </div>
      </div>

      <div className="mt-6 space-y-6">
        {(actionError || retryError) && (
          <Notice tone="error" role="alert" title={actionError ?? retryError ?? ""} />
        )}
        {run.unsaved && (
          <Notice tone="error" role="alert" title="The run finished, but its report could not be saved on the server.">
            Nothing from this run is kept. Use Retry to run it again once the server's storage is working.
          </Notice>
        )}
        {error && view && (
          <Notice tone="error" role="alert" title="Lost the live connection to this run.">
            {error.message}{" "}
            <button type="button" className="underline" onClick={run.reload}>
              Reconnect
            </button>
          </Notice>
        )}
        {view?.mode === "live" && !terminal && (
          <p className="text-sm text-muted">
            Live runs usually take one to two minutes{config ? ` and stop by ${Math.round(config.limits.run_deadline_s / 60)} minutes` : ""}.
            You can leave this page; the run continues on the server.
          </p>
        )}

        {!view ? (
          <p role="status" className="text-muted">
            Loading run…
          </p>
        ) : report ? (
          <>
            <Report report={report} />
            <details className="rounded-xl border border-line p-4">
              <summary className="cursor-pointer text-sm font-medium">Run progress and activity</summary>
              <div className="mt-4">
                <RunProgress run={run} />
              </div>
            </details>
          </>
        ) : terminal ? (
          <>
            <Notice
              tone={status === "cancelled" ? "info" : "error"}
              role={status === "cancelled" ? "status" : "alert"}
              title={status === "cancelled" ? "This run was cancelled before a report was written." : "This run ended without a report."}
            >
              {view.error ?? (view.stop_reason ? STOP_REASON_TEXT[view.stop_reason] : null)}
            </Notice>
            <RunProgress run={run} />
          </>
        ) : (
          <RunProgress run={run} />
        )}
      </div>
    </div>
  );
}

export function Workspace({ runId, sampleId }: { runId: string | null; sampleId: string | null }) {
  const [config, setConfig] = useState<ServerConfig | null>(null);
  const [samples, setSamples] = useState<SampleQuestion[] | null>(null);
  const [needsToken, setNeedsToken] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoadError(null);
    Promise.all([api.config(), api.samples()])
      .then(([c, s]) => {
        if (!active) return;
        setConfig(c);
        setSamples(s);
        setNeedsToken(false);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) setNeedsToken(true);
        else setLoadError(errorText(err));
        setSamples([]);
      });
    return () => {
      active = false;
    };
  }, [attempt]);

  if (needsToken) {
    return (
      <div className="px-4 py-14 sm:px-6">
        <TokenPrompt onSaved={() => setAttempt((n) => n + 1)} />
      </div>
    );
  }

  return (
    <>
      {loadError && (
        <div className="mx-auto max-w-3xl px-4 pt-8 sm:px-6">
          <Notice tone="error" role="alert" title="Could not reach the server.">
            {loadError}{" "}
            <button type="button" className="underline" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </button>
          </Notice>
        </div>
      )}
      {runId ? (
        <RunPage key={runId} runId={runId} config={config} />
      ) : sampleId ? (
        <SampleStarter sampleId={sampleId} samples={loadError ? [] : samples} />
      ) : (
        <NewResearch config={config} samples={samples ?? []} />
      )}
    </>
  );
}
