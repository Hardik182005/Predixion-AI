import { useEffect } from "react";

import { Page } from "./components/Layout";
import { Link, useLocation } from "./lib/router";
import { Landing } from "./pages/Landing";
import { Workspace } from "./pages/Workspace";

const RUN_PATH = /^\/research\/([A-Za-z0-9_-]{1,64})\/?$/;

function NotFound() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">Page not found</h1>
      <p className="mt-3 text-muted">There is nothing at this address.</p>
      <Link href="/" className="btn-primary mt-8">
        Go to the home page
      </Link>
    </div>
  );
}

export function App() {
  const { pathname, search } = useLocation();
  const runMatch = RUN_PATH.exec(pathname);

  useEffect(() => {
    document.title = pathname === "/" ? "Predixion AI" : pathname.startsWith("/research") ? "Research · Predixion AI" : "Not found · Predixion AI";
  }, [pathname]);

  let content;
  if (pathname === "/") content = <Landing />;
  else if (pathname === "/research" || pathname === "/research/") content = <Workspace runId={null} sampleId={search.get("sample")} />;
  else if (runMatch) content = <Workspace runId={runMatch[1] ?? null} sampleId={null} />;
  else content = <NotFound />;

  return <Page>{content}</Page>;
}
