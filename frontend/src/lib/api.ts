import type {
  ResearchRequest,
  RunSummary,
  RunView,
  SampleQuestion,
  ServerConfig,
  StartRunResponse,
} from "./types";

const TOKEN_KEY = "predixion.token";

/** API tokens live in sessionStorage only: they are cleared with the tab and never bundled. */
export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage can be unavailable (private mode); the token then lasts for this page only.
  }
}

const VISITOR_KEY = "predixion.visitor";
let pageVisitorId: string | null = null;

/**
 * A random id that scopes this browser's runs on a server that lets visitors in without a token.
 * It is not a credential: it only keeps one visitor's history apart from another's.
 */
export function visitorId(): string {
  try {
    const stored = localStorage.getItem(VISITOR_KEY);
    if (stored && /^[0-9a-f]{32}$/.test(stored)) return stored;
  } catch {
    // Storage can be unavailable (private mode); the id then lasts for this page only.
  }
  if (!pageVisitorId) {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    pageVisitorId = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    try {
      localStorage.setItem(VISITOR_KEY, pageVisitorId);
    } catch {
      // See above.
    }
  }
  return pageVisitorId;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : { "X-Visitor-Id": visitorId() };
}

/** Turns any non-2xx response into an ApiError with the server's error code and message. */
export async function errorFrom(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `Request failed (${response.status}).`;
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } };
    if (body.error?.code) code = body.error.code;
    if (body.error?.message) message = body.error.message;
  } catch {
    // Not JSON (a proxy error page, for example); keep the generic message.
  }
  return new ApiError(response.status, code, message);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...authHeaders(), ...init.headers },
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the Predixion API. Check that the server is running.");
  }
  if (!response.ok) throw await errorFrom(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  config: () => request<ServerConfig>("/api/config"),
  samples: () => request<SampleQuestion[]>("/api/samples"),
  listRuns: (limit = 10) => request<RunSummary[]>(`/api/runs?limit=${limit}`),
  getRun: (runId: string) => request<RunView>(`/api/runs/${encodeURIComponent(runId)}`),
  startRun: (body: ResearchRequest, idempotencyKey: string) =>
    request<StartRunResponse>("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    }),
  cancelRun: (runId: string) =>
    request<{ run_id: string; status: string }>(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }),
};

/** Downloads an export with the auth header (a plain link could not send it). */
export async function downloadExport(runId: string, format: "md" | "json"): Promise<void> {
  const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/export?format=${format}`, {
    headers: authHeaders(),
  }).catch(() => {
    throw new ApiError(0, "network_error", "Could not reach the Predixion API.");
  });
  if (!response.ok) throw await errorFrom(response);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `predixion-${runId}.${format}`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
