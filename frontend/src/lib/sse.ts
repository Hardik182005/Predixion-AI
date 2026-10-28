import { ApiError, authHeaders, errorFrom } from "./api";
import type { RunEvent } from "./types";

export interface SseMessage {
  id: string | null;
  event: string;
  data: string;
}

/**
 * Incremental parser for the text/event-stream format. Feed it decoded chunks in
 * any split; it calls onMessage once per complete event. Comments (": ping") and
 * the retry field are ignored.
 */
export function createSseParser(onMessage: (message: SseMessage) => void) {
  let buffer = "";
  let id: string | null = null;
  let event = "message";
  let data: string[] = [];

  function dispatch() {
    if (data.length > 0) onMessage({ id, event, data: data.join("\n") });
    id = null;
    event = "message";
    data = [];
  }

  function line(text: string) {
    if (text === "") return dispatch();
    if (text.startsWith(":")) return;
    const colon = text.indexOf(":");
    const field = colon === -1 ? text : text.slice(0, colon);
    let value = colon === -1 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") data.push(value);
    else if (field === "event") event = value;
    else if (field === "id") id = value;
  }

  return {
    push(chunk: string) {
      buffer += chunk;
      let match: RegExpExecArray | null;
      const newline = /\r\n|\r|\n/g;
      let start = 0;
      while ((match = newline.exec(buffer)) !== null) {
        // A lone "\r" at the end might be the first half of "\r\n"; wait for more input.
        if (match[0] === "\r" && match.index === buffer.length - 1) break;
        line(buffer.slice(start, match.index));
        start = match.index + match[0].length;
      }
      buffer = buffer.slice(start);
    },
  };
}

export function isTerminalEvent(event: RunEvent): boolean {
  return event.type === "status" && event.data?.terminal === true;
}

export interface StreamOptions {
  after: number;
  signal: AbortSignal;
  onEvent: (event: RunEvent) => void;
  onOpen?: () => void;
  onReconnecting?: (attempt: number) => void;
  maxAttempts?: number;
  backoffMs?: (attempt: number) => number;
}

const defaultBackoff = (attempt: number) => Math.min(10_000, 1000 * 2 ** (attempt - 1));

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

/**
 * Follows a run's event stream until its terminal status event. Uses fetch rather
 * than EventSource so it can send the Authorization header. If the connection drops,
 * it reconnects with Last-Event-ID so no event is applied twice. Resolves when the
 * run ends or the signal aborts; throws ApiError when the server refuses the stream
 * or reconnection keeps failing.
 */
export async function followRunEvents(runId: string, options: StreamOptions): Promise<void> {
  const { signal, onEvent, onOpen, onReconnecting, maxAttempts = 6, backoffMs = defaultBackoff } = options;
  let lastSeq = options.after;
  let failures = 0;

  while (!signal.aborted) {
    let finished = false;
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/events`, {
        headers: { Accept: "text/event-stream", "Last-Event-ID": String(lastSeq), ...authHeaders() },
        signal,
        cache: "no-store",
      });
      if (!response.ok) {
        const error = await errorFrom(response);
        // Client errors will not fix themselves; server errors and rate limits are retried below.
        if (response.status < 500 && response.status !== 429) throw error;
        throw Object.assign(error, { retryable: true });
      }
      if (!response.body) throw new ApiError(0, "stream_unsupported", "This browser cannot read streamed responses.");
      onOpen?.();
      failures = 0;

      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      const parser = createSseParser((message) => {
        if (message.event === "message" || !message.data) return;
        let event: RunEvent;
        try {
          event = JSON.parse(message.data) as RunEvent;
        } catch {
          return;
        }
        if (event.seq <= lastSeq) return;
        lastSeq = event.seq;
        onEvent(event);
        if (isTerminalEvent(event)) finished = true;
      });
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        parser.push(value);
        if (finished) {
          await reader.cancel().catch(() => undefined);
          break;
        }
      }
      if (finished) return;
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof ApiError && !(error as ApiError & { retryable?: boolean }).retryable) throw error;
    }
    // The stream ended before the run did: the network dropped or the server restarted.
    failures += 1;
    if (failures > maxAttempts) {
      throw new ApiError(0, "stream_lost", "Lost the connection to the run and could not reconnect.");
    }
    onReconnecting?.(failures);
    await sleep(backoffMs(failures), signal);
  }
}
