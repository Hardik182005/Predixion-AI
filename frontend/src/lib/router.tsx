import { type AnchorHTMLAttributes, type MouseEvent, useSyncExternalStore } from "react";

// A small history-API router: three routes do not justify a routing library.

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("popstate", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("popstate", listener);
  };
}

const snapshot = () => window.location.pathname + window.location.search + window.location.hash;

export function navigate(to: string, { replace = false } = {}) {
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  listeners.forEach((listener) => listener());
  const hash = to.split("#")[1];
  if (hash) document.getElementById(hash)?.scrollIntoView();
  else if (!replace) window.scrollTo(0, 0);
}

export function useLocation() {
  useSyncExternalStore(subscribe, snapshot);
  return { pathname: window.location.pathname, search: new URLSearchParams(window.location.search) };
}

export function Link({ href, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  function handle(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    const external = /^[a-z]+:/i.test(href);
    if (event.defaultPrevented || external || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) {
      return;
    }
    event.preventDefault();
    navigate(href);
  }
  return <a href={href} onClick={handle} {...rest} />;
}
