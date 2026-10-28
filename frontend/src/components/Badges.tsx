import type { ReactNode } from "react";

import { COVERAGE_LABEL, STATUS_LABEL, VERDICT_LABEL } from "../lib/format";
import type { CoverageStatus, Mode, RunStatus, SupportVerdict } from "../lib/types";

const pill = "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap";

export function VerdictBadge({ verdict }: { verdict: SupportVerdict }) {
  const style: Record<SupportVerdict, string> = {
    supported: "bg-ink text-white",
    partially_supported: "border border-ink text-ink",
    not_supported: "border border-danger text-danger",
    unchecked: "border border-dashed border-neutral-500 text-neutral-700",
  };
  return <span className={`${pill} ${style[verdict]}`}>{VERDICT_LABEL[verdict]}</span>;
}

export function CoverageBadge({ status }: { status: CoverageStatus }) {
  const style: Record<CoverageStatus, string> = {
    supported: "bg-ink text-white",
    weak: "border border-ink text-ink",
    conflicting: "border-2 border-ink text-ink",
    stale: "border border-dashed border-ink text-ink",
    missing: "border border-dashed border-neutral-500 text-neutral-700",
  };
  return <span className={`${pill} ${style[status]}`}>{COVERAGE_LABEL[status]}</span>;
}

export function StatusBadge({ status }: { status: RunStatus }) {
  const active = status === "queued" || status === "running";
  const bad = status === "failed" || status === "interrupted";
  return (
    <span
      className={`${pill} ${bad ? "border border-danger text-danger" : status === "completed" ? "bg-ink text-white" : "border border-ink text-ink"}`}
    >
      {active && <span aria-hidden="true" className="pulse-dot size-1.5 rounded-full bg-current" />}
      {STATUS_LABEL[status]}
    </span>
  );
}

export function ModeBadge({ mode }: { mode: Mode }) {
  return mode === "live" ? (
    <span className={`${pill} border border-ink text-ink`}>Live web research</span>
  ) : (
    <span className={`${pill} border border-dashed border-ink text-ink`} title="Synthetic sources; no web access or model calls">
      Fixture demo · synthetic sources
    </span>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
  role,
}: {
  tone?: "info" | "warning" | "error";
  title: string;
  children?: ReactNode;
  role?: "alert" | "status";
}) {
  const style = {
    info: "border-line bg-soft",
    warning: "border-ink bg-white",
    error: "border-danger bg-white",
  }[tone];
  return (
    <div role={role} className={`rounded-xl border-l-4 border ${style} p-4`}>
      <p className={`font-medium ${tone === "error" ? "text-danger" : ""}`}>{title}</p>
      {children && <div className="mt-1 text-sm text-neutral-700">{children}</div>}
    </div>
  );
}
