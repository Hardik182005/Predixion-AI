import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, setToken } from "./api";
import { formatCost, safeHttpUrl } from "./format";

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("turns the server's error envelope into an ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "rate_limited", message: "Too many runs. Try again shortly." } }), { status: 429 }),
      ),
    );
    await expect(api.startRun({ question: "q?" }, "key")).rejects.toMatchObject({
      status: 429,
      code: "rate_limited",
      message: "Too many runs. Try again shortly.",
    });
  });

  it("keeps a generic message when the error body is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>Bad gateway</html>", { status: 502 })));
    await expect(api.config()).rejects.toMatchObject({ status: 502, code: "http_error", message: "Request failed (502)." });
  });

  it("reports an unreachable server as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = await api.config().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 0, code: "network_error" });
  });

  it("sends the session token and the idempotency key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ run_id: "run_1", status: "queued", reused: false })));
    vi.stubGlobal("fetch", fetchMock);
    setToken("pdx_secret");
    await api.startRun({ question: "q?" }, "key-1");
    const headers = fetchMock.mock.calls[0]![1].headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer pdx_secret");
    expect(headers["Idempotency-Key"]).toBe("key-1");
    expect(headers["X-Visitor-Id"]).toBeUndefined();
  });

  it("sends the same random visitor id on every request when there is no token", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}")));
    vi.stubGlobal("fetch", fetchMock);
    setToken(null);
    await api.config();
    await api.samples();
    const [first, second] = fetchMock.mock.calls.map((call) => call[1].headers as Record<string, string>);
    expect(first!["X-Visitor-Id"]).toMatch(/^[0-9a-f]{32}$/);
    expect(second!["X-Visitor-Id"]).toBe(first!["X-Visitor-Id"]);
    expect(first!.Authorization).toBeUndefined();
  });
});

describe("format", () => {
  it("only allows http and https links", () => {
    expect(safeHttpUrl("https://example.com/a?b=1")).toBe("https://example.com/a?b=1");
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpUrl("JAVASCRIPT:alert(1)")).toBeNull();
    expect(safeHttpUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeHttpUrl("/relative")).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });

  it("formats small costs without rounding them to zero", () => {
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.0042)).toBe("$0.0042");
    expect(formatCost(0.1234, true)).toBe("about $0.123");
  });
});
