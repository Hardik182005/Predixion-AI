import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import { createSseParser, followRunEvents, isTerminalEvent, type SseMessage } from "./sse";
import type { RunEvent } from "./types";

function frame(event: Partial<RunEvent> & { seq: number }): string {
  const full: RunEvent = { ts: "2026-10-28T10:00:00Z", type: "stage", stage: null, message: "m", data: null, ...event };
  return `id: ${full.seq}\nevent: ${full.type}\ndata: ${JSON.stringify(full)}\n\n`;
}

function streamResponse(chunks: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const terminal = { type: "status" as const, data: { status: "completed", terminal: true } };

afterEach(() => vi.unstubAllGlobals());

describe("createSseParser", () => {
  it("parses events split across chunks, CRLF line endings, comments, and multi-line data", () => {
    const messages: SseMessage[] = [];
    const parser = createSseParser((m) => messages.push(m));
    parser.push("retry: 3000\r\n\r\n: ping\r\n\r\nid: 1\r\nevent: sta");
    parser.push("ge\r\ndata: {\"a\":1}\r");
    parser.push("\n\r\nid: 2\nevent: plan\ndata: line one\ndata: line two\n\n");
    expect(messages).toEqual([
      { id: "1", event: "stage", data: '{"a":1}' },
      { id: "2", event: "plan", data: "line one\nline two" },
    ]);
  });

  it("recognizes only status events marked terminal", () => {
    const base: RunEvent = { seq: 1, ts: "", type: "status", stage: null, message: "", data: { terminal: true } };
    expect(isTerminalEvent(base)).toBe(true);
    expect(isTerminalEvent({ ...base, data: { status: "running" } })).toBe(false);
    expect(isTerminalEvent({ ...base, type: "report" })).toBe(false);
  });
});

describe("followRunEvents", () => {
  it("reconnects with Last-Event-ID after a drop and never applies an event twice", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(streamResponse([frame({ seq: 1 }), frame({ seq: 2 })]))
      .mockResolvedValueOnce(streamResponse([frame({ seq: 2 }), frame({ seq: 3, ...terminal })]));
    vi.stubGlobal("fetch", fetchMock);

    const seen: number[] = [];
    const reconnects: number[] = [];
    await followRunEvents("run_abc", {
      after: 0,
      signal: new AbortController().signal,
      onEvent: (e) => seen.push(e.seq),
      onReconnecting: (n) => reconnects.push(n),
      backoffMs: () => 0,
    });

    expect(seen).toEqual([1, 2, 3]);
    expect(reconnects).toEqual([1]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]![1].headers["Last-Event-ID"]).toBe("2");
  });

  it("retries server errors but gives up after the attempt limit", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response("", { status: 503 })));
    await expect(
      followRunEvents("run_abc", { after: 0, signal: new AbortController().signal, onEvent: () => {}, maxAttempts: 2, backoffMs: () => 0 }),
    ).rejects.toMatchObject({ code: "stream_lost" });
  });

  it("does not retry client errors such as an unknown run", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ error: { code: "not_found", message: "Run not found." } }), { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    const error = await followRunEvents("run_x", { after: 0, signal: new AbortController().signal, onEvent: () => {} }).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, code: "not_found", message: "Run not found." });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
