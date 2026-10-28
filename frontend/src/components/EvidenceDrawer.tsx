import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { formatDate, formatDateTime, safeHttpUrl } from "../lib/format";
import type { Evidence, ResearchReport, Source } from "../lib/types";

interface EvidenceContextValue {
  open: (evidenceId: string) => void;
  has: (evidenceId: string) => boolean;
}

const EvidenceContext = createContext<EvidenceContextValue>({ open: () => undefined, has: () => false });

export const useEvidence = () => useContext(EvidenceContext);

/** Provides citation lookups for a report and renders the evidence drawer. */
export function EvidenceProvider({ report, children }: { report: ResearchReport; children: ReactNode }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const evidence = useMemo(() => new Map(report.evidence.map((e) => [e.id, e])), [report.evidence]);
  const sources = useMemo(() => new Map(report.sources.map((s) => [s.id, s])), [report.sources]);

  const open = useCallback((id: string) => {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOpenId(id);
  }, []);
  const close = useCallback(() => setOpenId(null), []);
  useEffect(() => {
    // Return focus to the citation once the modal is gone (the page is inert while it is open).
    if (openId === null && returnFocus.current) {
      returnFocus.current.focus();
      returnFocus.current = null;
    }
  }, [openId]);
  const value = useMemo(() => ({ open, has: (id: string) => evidence.has(id) }), [open, evidence]);

  const item = openId ? evidence.get(openId) : undefined;
  return (
    <EvidenceContext.Provider value={value}>
      {children}
      {item && <EvidenceDrawer evidence={item} source={sources.get(item.source_id)} report={report} onClose={close} />}
    </EvidenceContext.Provider>
  );
}

function sourceCaveats(evidence: Evidence, source: Source | undefined): string[] {
  const notes: string[] = [];
  if (evidence.polarity === "contradicts") notes.push("This passage contradicts the statement it is attached to.");
  if (evidence.first_party) notes.push("First-party source: the organization describing its own product or work.");
  if (source?.fixture) notes.push("Synthetic fixture source written for the demo. It is not a real web page.");
  if (source?.injection_suspected) {
    notes.push("This page contained text that looked like instructions to an AI. It was treated as data and not followed.");
  }
  if (!source?.published_at) notes.push("Publication date unknown.");
  else if (source.published_at_origin === "provider_estimate") notes.push("Publication date is the search provider's estimate.");
  notes.push("The quote is an excerpt. Read the source for its full context.");
  return notes;
}

function EvidenceDrawer({
  evidence,
  source,
  report,
  onClose,
}: {
  evidence: Evidence;
  source: Source | undefined;
  report: ResearchReport;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const href = safeHttpUrl(source?.url);
  const criteria = new Map((report.plan?.criteria ?? []).map((c) => [c.id, c.description]));

  useEffect(() => {
    const node = dialog.current;
    if (node && !node.open) node.showModal();
  }, []);

  return (
    <dialog
      ref={dialog}
      className="drawer"
      aria-labelledby="evidence-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose(); // backdrop click
      }}
    >
      <div className="flex h-full flex-col bg-white">
        <div className="flex items-start justify-between gap-4 border-b border-line p-5">
          <div>
            <p className="eyebrow">Evidence {evidence.id}</p>
            <h2 id="evidence-title" className="mt-1 text-lg leading-snug font-semibold">
              {source?.title || source?.domain || "Unknown source"}
            </h2>
          </div>
          <button type="button" className="btn-quiet -mt-1 -mr-2 px-2" onClick={onClose} aria-label="Close evidence">
            <svg aria-hidden="true" viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M5 5l10 10M15 5L5 15" />
            </svg>
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto p-5">
          <section aria-labelledby="ev-passage">
            <h3 id="ev-passage" className="eyebrow">
              Passage
            </h3>
            <blockquote className="mt-2 border-l-2 border-ink pl-4 leading-relaxed whitespace-pre-line">{evidence.quote}</blockquote>
          </section>

          <section aria-labelledby="ev-claim">
            <h3 id="ev-claim" className="eyebrow">
              What it is used to support
            </h3>
            <p className="mt-2 text-sm leading-relaxed">{evidence.claim}</p>
            {evidence.criterion_ids.length > 0 && (
              <p className="mt-2 text-sm text-muted">
                Criteria: {evidence.criterion_ids.map((id) => criteria.get(id) ?? id).join("; ")}
              </p>
            )}
            {evidence.entity && <p className="mt-1 text-sm text-muted">About: {evidence.entity}</p>}
          </section>

          <section aria-labelledby="ev-source">
            <h3 id="ev-source" className="eyebrow">
              Source
            </h3>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-muted">Site</dt>
              <dd className="break-words">{source?.domain ?? "Unknown"}</dd>
              <dt className="text-muted">Type</dt>
              <dd>{source ? source.kind.replaceAll("_", " ") : "Unknown"}</dd>
              <dt className="text-muted">Published</dt>
              <dd>{formatDate(source?.published_at)}</dd>
              <dt className="text-muted">Retrieved</dt>
              <dd>{formatDateTime(source?.retrieved_at)}</dd>
            </dl>
            {href ? (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="btn-secondary mt-4 max-w-full"
              >
                <span className="truncate">Open source</span>
                <span className="sr-only"> (opens {source?.domain} in a new tab)</span>
              </a>
            ) : (
              <p className="mt-3 text-sm text-muted">No safe link is available for this source.</p>
            )}
          </section>

          <section aria-labelledby="ev-limits">
            <h3 id="ev-limits" className="eyebrow">
              Limitations
            </h3>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-neutral-700">
              {sourceCaveats(evidence, source).map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </dialog>
  );
}

/** Citation chips: each opens its evidence in the drawer. Unknown IDs render inert and flagged. */
export function Citations({ ids }: { ids: string[] }) {
  const { open, has } = useEvidence();
  if (ids.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {ids.map((id) =>
        has(id) ? (
          <button
            key={id}
            type="button"
            onClick={() => open(id)}
            className="rounded border border-ink px-1.5 font-mono text-[11px] leading-5 hover:bg-ink hover:text-white"
            aria-label={`Show evidence ${id}`}
            aria-haspopup="dialog"
          >
            {id}
          </button>
        ) : (
          <span key={id} className="rounded border border-dashed border-danger px-1.5 font-mono text-[11px] leading-5 text-danger">
            {id} missing
          </span>
        ),
      )}
    </span>
  );
}
