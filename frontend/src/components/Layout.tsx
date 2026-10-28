import type { ReactNode } from "react";

import { Link, useLocation } from "../lib/router";

export const GITHUB_URL = "https://github.com/Hardik182005/Predixion-AI";

export function Logo() {
  return (
    <span className="flex items-center gap-2 font-semibold tracking-tight">
      <svg aria-hidden="true" viewBox="0 0 32 32" className="size-6">
        <rect width="32" height="32" rx="7" fill="currentColor" />
        <path d="M10 23V9h7a5 5 0 0 1 0 10h-7" fill="none" stroke="#fff" strokeWidth="3" strokeLinejoin="round" />
      </svg>
      Predixion AI
    </span>
  );
}

export function Header() {
  const { pathname } = useLocation();
  const navLink = "rounded-md px-2.5 py-1.5 text-sm text-muted hover:text-ink";
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-white/90 backdrop-blur">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" aria-label="Predixion AI home" className="rounded-md text-ink">
          <Logo />
        </Link>
        <nav aria-label="Main" className="flex items-center gap-1">
          <Link
            href="/research"
            className={navLink}
            aria-current={pathname.startsWith("/research") ? "page" : undefined}
          >
            Research
          </Link>
          <Link href="/#how-it-works" className={`${navLink} hidden sm:inline-flex`}>
            How it works
          </Link>
          <a href={GITHUB_URL} className={navLink} target="_blank" rel="noopener noreferrer">
            GitHub<span className="sr-only"> (opens in a new tab)</span>
          </a>
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-8 text-sm text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <Logo />
        <p>Answers come with the passages that support them. Check the sources before you rely on a result.</p>
      </div>
    </footer>
  );
}

export function Page({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <Header />
      <main id="main" tabIndex={-1} className="flex-1 outline-none">
        {children}
      </main>
      <Footer />
    </div>
  );
}
