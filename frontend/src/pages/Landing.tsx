import { EvidenceStack } from "../components/EvidenceStack";
import { Link } from "../lib/router";

export const SAMPLE_ID = "vector_databases";

const STEPS = [
  {
    title: "Plan",
    body: "The question becomes a short list of criteria a useful answer must establish, and the searches that should find them. Ambiguous questions get a stated interpretation.",
  },
  {
    title: "Search and read",
    body: "Results are filtered and de-duplicated, unsafe links are dropped, and the most promising pages are read in full. Page text is treated as data, never as instructions.",
  },
  {
    title: "Extract evidence",
    body: "Each piece of evidence is a passage quoted from a page. A quote that does not appear in the page word for word is rejected.",
  },
  {
    title: "Fill the gaps",
    body: "Coverage is assessed per criterion. Missing or weak criteria trigger targeted follow-up searches until the criteria are met or a limit is reached.",
  },
  {
    title: "Write and verify",
    body: "The answer cites evidence IDs. Every claim is checked against the passages it cites; unsupported claims are removed or qualified before you see them.",
  },
];

const ANATOMY = [
  ["Short answer", "Two to four sentences that answer the question and name the main uncertainty."],
  ["Findings with citations", "Each citation opens the quoted passage, its source, date, and caveats."],
  ["Criteria coverage", "Which parts of the question have support, weak support, conflicting sources, or none."],
  ["Conflicts and gaps", "Where sources disagree and what could not be found, stated plainly."],
  ["Confidence and next steps", "How much to rely on the result and what would resolve what remains open."],
  ["Execution details", "Searches, pages read, model calls, tokens, cost, and timings for the run."],
];

export function Landing() {
  return (
    <>
      <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 pt-16 pb-12 sm:px-6 lg:grid-cols-[1.15fr_1fr] lg:pt-24">
        <div>
          <p className="eyebrow">Research agent</p>
          <h1 className="mt-4 text-4xl leading-[1.1] font-semibold tracking-tight text-balance sm:text-5xl">
            Clear answers. Evidence you can inspect.
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">
            Research complex questions, compare sources, and understand what supports each conclusion.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/research" className="btn-primary">
              Start research
            </Link>
            <Link href={`/research?sample=${SAMPLE_ID}`} className="btn-secondary">
              View sample
            </Link>
          </div>
          <p className="mt-4 text-sm text-muted">The sample runs in fixture mode: synthetic sources, no web access, no cost.</p>
        </div>
        <EvidenceStack />
      </section>

      <section id="how-it-works" aria-labelledby="how-title" className="scroll-mt-20 border-t border-line bg-soft">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 id="how-title" className="text-2xl font-semibold tracking-tight sm:text-3xl">
            How it works
          </h2>
          <p className="mt-3 max-w-2xl leading-relaxed text-muted">
            A fixed sequence of stages with explicit limits on rounds, pages, time, and cost. You can watch each stage as it runs.
          </p>
          <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {STEPS.map((step, i) => (
              <li key={step.title} className="card p-5">
                <span aria-hidden="true" className="font-mono text-xs text-muted">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h3 className="mt-2 font-semibold">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-700">{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section aria-labelledby="anatomy-title" className="border-t border-line">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[1fr_1.4fr]">
          <div>
            <h2 id="anatomy-title" className="text-2xl font-semibold tracking-tight sm:text-3xl">
              What a report contains
            </h2>
            <p className="mt-3 leading-relaxed text-muted">
              Reports are built to be checked, not just read. When the evidence is thin, the report says so instead of filling the gap.
            </p>
          </div>
          <dl className="grid gap-x-8 gap-y-6 sm:grid-cols-2">
            {ANATOMY.map(([term, detail]) => (
              <div key={term} className="border-t border-ink pt-3">
                <dt className="font-semibold">{term}</dt>
                <dd className="mt-1 text-sm leading-relaxed text-neutral-700">{detail}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section aria-labelledby="limits-title" className="border-t border-line bg-ink text-white">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 id="limits-title" className="text-2xl font-semibold tracking-tight sm:text-3xl">
            What it does not do
          </h2>
          <ul className="mt-6 grid gap-4 text-sm leading-relaxed text-neutral-300 sm:grid-cols-3">
            <li>
              <span className="block font-semibold text-white">It can still be wrong.</span>
              Verification checks that a claim matches its quoted passages, not that the source itself is correct.
            </li>
            <li>
              <span className="block font-semibold text-white">It only sees the open web.</span>
              Paywalled, private, and very recent pages are often missing, and search results vary between runs.
            </li>
            <li>
              <span className="block font-semibold text-white">It works within limits.</span>
              Each run has caps on rounds, pages, time, and cost, and stops with a partial answer when it reaches one.
            </li>
          </ul>
          <Link href="/research" className="btn mt-10 bg-white text-ink hover:bg-neutral-200">
            Start research
          </Link>
        </div>
      </section>
    </>
  );
}
