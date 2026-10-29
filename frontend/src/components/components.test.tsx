import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ResearchReport, ServerConfig } from "../lib/types";
import type { RunState } from "../lib/useRun";
import hrtechJson from "../test/report-hrtech.json";
import sqliteJson from "../test/report-sqlite.json";
import vectorJson from "../test/report-vector.json";
import { sourceDependencies } from "./EvidenceDrawer";
import { QuestionForm } from "./QuestionForm";
import { Report, shortCriterion } from "./Report";
import { RunProgress } from "./RunProgress";

const fixture = (json: unknown) => structuredClone(json) as ResearchReport;

describe("Report", () => {
  it("renders the answer, findings, and a comparison table with one row per option", () => {
    render(<Report report={fixture(vectorJson)} />);
    expect(screen.getByRole("heading", { name: "Short answer" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Key findings" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["Qdrant", "Milvus", "Weaviate"]);
    expect(screen.queryByText(/Partial answer/)).not.toBeInTheDocument();
  });

  it("flags a partial answer, conflicting sources, and missing evidence", () => {
    render(<Report report={fixture(sqliteJson)} />);
    expect(screen.getByText("Partial answer: some criteria lack verified evidence.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sources disagree" })).toBeInTheDocument();
    expect(screen.getByText("Missing evidence")).toBeInTheDocument();
  });

  it("lists matching organizations and keeps excluded candidates separate", () => {
    render(<Report report={fixture(hrtechJson)} />);
    const section = screen.getByRole("region", { name: "Matching organizations" });
    expect(within(section).getByText("Darwinbox")).toBeInTheDocument();
    expect(within(section).getByText("Considered but excluded (1)")).toBeInTheDocument();
    expect(within(section).getByText("Deel")).toBeInTheDocument();
  });

  it("opens the cited passage in a dialog and returns focus to the citation when it closes", async () => {
    const user = userEvent.setup();
    const report = fixture(vectorJson);
    render(<Report report={report} />);
    const citation = screen.getAllByRole("button", { name: "Show evidence E1" })[0]!;
    await user.click(citation);

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(report.evidence[0]!.quote)).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /Open source/ })).toHaveAttribute("rel", "noopener noreferrer nofollow");

    fireEvent(dialog, new Event("cancel", { cancelable: true })); // what Escape triggers on a modal dialog
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(citation).toHaveFocus();

    await user.click(citation);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close evidence" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(citation).toHaveFocus();
  });

  it("renders hostile page content as inert text and never links unsafe URLs", async () => {
    const user = userEvent.setup();
    const report = fixture(vectorJson);
    const finding = report.key_findings[0]!;
    finding.text = '<script>alert("x")</script><img src=x onerror=alert(1)>';
    const source = report.sources.find((s) => s.id === report.evidence.find((e) => e.id === finding.evidence_ids[0])!.source_id)!;
    source.url = "javascript:alert(1)";
    const { container } = render(<Report report={report} />);

    expect(screen.getByText(finding.text)).toBeInTheDocument();
    expect(container.querySelector("script, img")).toBeNull();

    await user.click(screen.getAllByRole("button", { name: `Show evidence ${finding.evidence_ids[0]}` })[0]!);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("link")).not.toBeInTheDocument();
    expect(within(dialog).getByText("No safe link is available for this source.")).toBeInTheDocument();
    expect(document.querySelector('a[href^="javascript"]')).toBeNull();
  });

  it("marks a citation to unknown evidence instead of linking it", () => {
    const report = fixture(vectorJson);
    report.key_findings[0]!.evidence_ids = ["E999"];
    render(<Report report={report} />);
    expect(screen.getByText("E999 missing")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show evidence E999" })).not.toBeInTheDocument();
  });

  it("lists the models a run used and counts fallbacks", () => {
    const report = fixture(vectorJson);
    report.execution.metrics.model_fallbacks = 1;
    report.execution.metrics.models_used = { "groq:openai/gpt-oss-120b": 1, "openai:gpt-test": 7 };
    render(<Report report={report} />);
    expect(screen.getByText(/1 fallback\)/)).toBeInTheDocument();
    expect(screen.getByText("groq:openai/gpt-oss-120b (1 call), openai:gpt-test (7 calls)")).toBeInTheDocument();
  });
});

const config: ServerConfig = {
  version: "test",
  default_mode: "live",
  live_available: false,
  live_needs_token: false,
  model: "gpt-test",
  auth_mode: "none",
  fault_injection: false,
  limits: {
    question_min_chars: 10,
    question_max_chars: 2000,
    max_rounds: 3,
    max_pages_per_run: 12,
    run_deadline_s: 180,
    max_cost_usd_per_run: 0.5,
  },
};

describe("QuestionForm", () => {
  it("shows a validation error as an alert and does not submit", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<QuestionForm config={config} samples={[]} busy={false} error={null} onSubmit={onSubmit} />);
    await user.type(screen.getByLabelText("Research question"), "short");
    await user.click(screen.getByRole("button", { name: "Start research" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a question of at least 10 characters.");
    expect(screen.getByLabelText("Research question")).toHaveAttribute("aria-invalid", "true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables live mode with a reason when the server has no credentials, and submits fixture mode", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const samples = [{ id: "s1", question: "Which vector database suits a small RAG product?" }];
    render(<QuestionForm config={config} samples={samples} busy={false} error={null} onSubmit={onSubmit} />);
    const live = screen.getByRole("radio", { name: /Live web research/ });
    expect(live).toBeDisabled();
    expect(live).toHaveAccessibleDescription("Unavailable: the server has no search or model credentials configured.");
    expect(screen.getByRole("radio", { name: /Fixture demo/ })).toBeChecked();
    expect(screen.queryByText("Advanced: simulate a failure (testing)")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: samples[0]!.question }));
    await user.click(screen.getByRole("button", { name: "Start research" }));
    expect(onSubmit).toHaveBeenCalledWith({ question: samples[0]!.question, mode: "fixture" });
  });

  it("explains that live research needs a token and offers to enter one", async () => {
    const user = userEvent.setup();
    const onRequestToken = vi.fn();
    render(
      <QuestionForm
        config={{ ...config, live_available: true, live_needs_token: true, default_mode: "fixture" }}
        samples={[]}
        busy={false}
        error={null}
        onSubmit={vi.fn()}
        onRequestToken={onRequestToken}
      />,
    );
    const live = screen.getByRole("radio", { name: /Live web research/ });
    expect(live).toBeDisabled();
    expect(live).toHaveAccessibleDescription(expect.stringContaining("Needs an access token"));
    expect(screen.getByRole("radio", { name: /Fixture demo/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Enter an access token" }));
    expect(onRequestToken).toHaveBeenCalledOnce();
  });

  it("offers failure simulation only when the server enables it", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <QuestionForm
        config={{ ...config, fault_injection: true }}
        samples={[]}
        busy={false}
        error={null}
        initialQuestion="What changed in the latest SQLite release?"
        onSubmit={onSubmit}
      />,
    );
    await user.click(screen.getByText("Advanced: simulate a failure (testing)"));
    await user.selectOptions(screen.getByLabelText("Inject a provider failure to see how the run degrades."), "Search provider is down");
    await user.click(screen.getByRole("button", { name: "Start research" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ fault: { search: "unavailable" } }));
  });

  it("shows a server error as an alert", () => {
    render(<QuestionForm config={config} samples={[]} busy={false} error="Too many runs. Try again shortly." onSubmit={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Too many runs. Try again shortly.");
  });
});

function runState(overrides: Partial<RunState & { terminal: boolean }>): RunState & { terminal: boolean } {
  return {
    view: null,
    status: "running",
    events: [],
    plan: null,
    coverage: [],
    stagesSeen: [],
    currentStage: null,
    connection: "live",
    reconnectAttempt: 0,
    error: null,
    unsaved: false,
    terminal: false,
    ...overrides,
  };
}

describe("RunProgress", () => {
  it("marks the current stage and never shows a percentage", () => {
    const { container } = render(
      <RunProgress run={runState({ stagesSeen: ["validate", "plan", "search"], currentStage: "search" })} />,
    );
    expect(screen.getByText("Search").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Current stage: Search")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d\s*%/);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("labels skipped optional stages as not needed once the run ends", () => {
    const seen = ["validate", "plan", "search", "filter", "read", "extract", "assess", "synthesize", "verify", "finalize"] as const;
    render(<RunProgress run={runState({ status: "completed", terminal: true, stagesSeen: [...seen], currentStage: "finalize" })} />);
    expect(screen.getByText("Follow up").closest("li")).toHaveTextContent("Not needed");
    expect(screen.getByText("Repair claims").closest("li")).toHaveTextContent("Not needed");
    expect(screen.getByText("Write answer").closest("li")).toHaveTextContent("Done");
    expect(screen.getByText("Research finished.")).toBeInTheDocument();
  });

  it("tells the user when it is reconnecting", () => {
    render(<RunProgress run={runState({ connection: "reconnecting", reconnectAttempt: 2 })} />);
    expect(screen.getByRole("status", { name: "" })).toBeDefined();
    expect(screen.getByText("Connection lost. Reconnecting…")).toBeInTheDocument();
    expect(screen.getByText(/Attempt 2\./)).toBeInTheDocument();
  });
});

describe("evidence helpers", () => {
  it("shortens comparison headers but keeps short ones whole", () => {
    expect(shortCriterion("Licensing: whether the license permits proprietary use without viral obligations")).toBe("Licensing");
    expect(shortCriterion("Open-source license")).toBe("Open-source license");
    const long = shortCriterion("Community and ecosystem including release cadence, connectors and documentation quality");
    expect(long.length).toBeLessThanOrEqual(49);
    expect(long.endsWith("…")).toBe(true);
  });

  it("lists which claims depend on a source without calling anything", () => {
    const report = vectorJson as unknown as ResearchReport;
    const sourceId = report.evidence[0]!.source_id;
    const deps = sourceDependencies(report, sourceId);
    const sourceOf = new Map(report.evidence.map((e) => [e.id, e.source_id]));
    for (const id of deps.only) {
      const claim = report.claims!.find((c) => c.id === id)!;
      expect(claim.evidence_ids.every((e) => sourceOf.get(e) === sourceId)).toBe(true);
    }
    for (const id of deps.shared) {
      const claim = report.claims!.find((c) => c.id === id)!;
      expect(claim.evidence_ids.some((e) => sourceOf.get(e) === sourceId)).toBe(true);
      expect(claim.evidence_ids.every((e) => sourceOf.get(e) === sourceId)).toBe(false);
    }
    expect(sourceDependencies(report, "S999")).toEqual({ only: [], shared: [] });
  });
});
