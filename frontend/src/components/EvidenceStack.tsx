import { useEffect, useRef, useState } from "react";

/**
 * Decorative hero: three stacked cards (a source, a quoted passage, a verdict)
 * illustrating what a report is made of. The content is illustrative and hidden
 * from assistive technology. Animation pauses when the stack is offscreen.
 */
export function EvidenceStack() {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry?.isIntersecting ?? true), { threshold: 0 });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div aria-hidden="true" className="evidence-stage mx-auto w-full max-w-sm py-16 pr-12">
      <div ref={ref} className={`evidence-stack h-64 ${visible ? "" : "is-paused"}`} data-testid="evidence-stack">
        <div className="evidence-card p-5" data-depth="2">
          <p className="font-mono text-[11px] tracking-wider text-neutral-400 uppercase">Verification</p>
          <p className="mt-3 text-sm leading-relaxed">Each claim is checked against the passages it cites.</p>
          <div className="mt-5 flex gap-2 text-[11px]">
            <span className="rounded-full bg-white px-2 py-0.5 font-medium text-ink">Supported</span>
            <span className="rounded-full border border-neutral-500 px-2 py-0.5">Partly supported</span>
          </div>
        </div>
        <div className="evidence-card p-5" data-depth="1">
          <p className="font-mono text-[11px] tracking-wider text-muted uppercase">Passage · E2</p>
          <p className="mt-3 border-l-2 border-ink pl-3 text-sm leading-relaxed text-neutral-700">
            “The quoted text must appear in the source it cites, word for word.”
          </p>
        </div>
        <div className="evidence-card flex flex-col p-5" data-depth="0">
          <p className="font-mono text-[11px] tracking-wider text-muted uppercase">Source · S1</p>
          <p className="mt-3 font-medium">Official documentation</p>
          <p className="text-sm text-muted">docs.example.org · read and dated</p>
          <div className="mt-auto space-y-2">
            <div className="h-2 w-11/12 rounded bg-soft" />
            <div className="h-2 w-9/12 rounded bg-soft" />
            <div className="h-2 w-10/12 rounded bg-soft" />
          </div>
        </div>
      </div>
    </div>
  );
}
