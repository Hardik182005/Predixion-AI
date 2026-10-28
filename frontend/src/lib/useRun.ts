import { useEffect, useReducer, useState } from "react";

import { ApiError, api } from "./api";
import { followRunEvents } from "./sse";
import type { CoverageStatus, RunEvent, RunStatus, RunView, Stage } from "./types";
import { TERMINAL_STATUSES } from "./types";

export type Connection = "idle" | "connecting" | "live" | "reconnecting" | "closed";

export interface PlanSummary {
  interpretation: string;
  ambiguity_note: string | null;
  criteria: { id: string; description: string; kind: string; required: boolean }[];
  queries: { id: string; text: string }[];
}

export interface LiveCoverage {
  criterion_id: string;
  status: CoverageStatus;
  evidence: number;
}

export interface RunState {
  view: RunView | null;
  status: RunStatus | null;
  events: RunEvent[];
  plan: PlanSummary | null;
  coverage: LiveCoverage[];
  stagesSeen: Stage[];
  currentStage: Stage | null;
  connection: Connection;
  reconnectAttempt: number;
  error: ApiError | null;
  /** The run ended but the server could not save its report (terminal event with persisted: false). */
  unsaved: boolean;
}

type Action =
  | { type: "reset" }
  | { type: "view"; view: RunView }
  | { type: "event"; event: RunEvent }
  | { type: "connection"; connection: Connection; attempt?: number }
  | { type: "error"; error: ApiError };

const initial: RunState = {
  view: null,
  status: null,
  events: [],
  plan: null,
  coverage: [],
  stagesSeen: [],
  currentStage: null,
  connection: "idle",
  reconnectAttempt: 0,
  error: null,
  unsaved: false,
};

const MAX_EVENTS_KEPT = 500;

function reducer(state: RunState, action: Action): RunState {
  switch (action.type) {
    case "reset":
      return initial;
    case "view": {
      const { view } = action;
      const plan = view.plan ?? view.report?.plan ?? null;
      return { ...state, view, status: view.status, plan: plan ?? state.plan };
    }
    case "event": {
      const { event } = action;
      const next: RunState = { ...state, events: [...state.events, event].slice(-MAX_EVENTS_KEPT) };
      const data = event.data ?? {};
      if (event.type === "status" && typeof data.status === "string") next.status = data.status as RunStatus;
      if (event.type === "status" && data.terminal === true && data.persisted === false) next.unsaved = true;
      if (event.type === "stage" && event.stage) {
        next.currentStage = event.stage;
        if (!state.stagesSeen.includes(event.stage)) next.stagesSeen = [...state.stagesSeen, event.stage];
      }
      if (event.type === "plan" && Array.isArray(data.criteria) && !state.view?.plan) {
        next.plan = {
          interpretation: String(data.interpretation ?? ""),
          ambiguity_note: typeof data.ambiguity_note === "string" ? data.ambiguity_note : null,
          criteria: data.criteria as PlanSummary["criteria"],
          queries: Array.isArray(data.queries) ? (data.queries as PlanSummary["queries"]) : (state.plan?.queries ?? []),
        };
      }
      if (event.type === "coverage" && Array.isArray(data.coverage)) next.coverage = data.coverage as LiveCoverage[];
      return next;
    }
    case "connection":
      return { ...state, connection: action.connection, reconnectAttempt: action.attempt ?? 0 };
    case "error":
      return { ...state, error: action.error, connection: "closed" };
  }
}

/** Loads a run, follows its event stream to the end, then loads the final report. */
export function useRun(runId: string | null) {
  const [state, dispatch] = useReducer(reducer, initial);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    dispatch({ type: "reset" });
    if (!runId) return;
    const controller = new AbortController();
    const { signal } = controller;

    (async () => {
      try {
        dispatch({ type: "view", view: await api.getRun(runId) });
        if (signal.aborted) return;
        dispatch({ type: "connection", connection: "connecting" });
        await followRunEvents(runId, {
          after: 0,
          signal,
          onEvent: (event) => dispatch({ type: "event", event }),
          onOpen: () => dispatch({ type: "connection", connection: "live" }),
          onReconnecting: (attempt) => dispatch({ type: "connection", connection: "reconnecting", attempt }),
        });
        if (signal.aborted) return;
        dispatch({ type: "view", view: await api.getRun(runId) });
        dispatch({ type: "connection", connection: "closed" });
      } catch (error) {
        if (signal.aborted) return;
        dispatch({
          type: "error",
          error: error instanceof ApiError ? error : new ApiError(0, "unexpected", "Something went wrong loading this run."),
        });
      }
    })();

    return () => controller.abort();
  }, [runId, reloadKey]);

  const terminal = state.status !== null && TERMINAL_STATUSES.has(state.status);
  return { ...state, terminal, reload: () => setReloadKey((k) => k + 1) };
}
