"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Which rows have come on screen (a little ahead of the scroll), so a page
 * reads per-row details for what people see, never for every row (design
 * system v2; orchestrator, 20 Oct: Calls read every row's report). Each row
 * carries data-call-row="<id>" and ref={observeRow}.
 *
 * Null where the browser can't tell (no IntersectionObserver), and under
 * test, where nothing scrolls: then every row counts, as before.
 */
export function useRowsInView(enabled: boolean) {
  const [seen, setSeen] = useState<Set<string> | null>(() =>
    typeof IntersectionObserver === "function" &&
    process.env.NODE_ENV !== "test"
      ? new Set()
      : null,
  );
  const observer = useRef<IntersectionObserver | null>(null);
  const rows = useRef(new Set<Element>());
  useEffect(() => {
    if (!enabled || seen === null) return;
    const watcher = new IntersectionObserver(
      (entries) => {
        const shown = entries
          .filter((entry) => entry.isIntersecting)
          .map((entry) => (entry.target as HTMLElement).dataset.callRow)
          .filter((id): id is string => Boolean(id));
        if (!shown.length) return;
        setSeen((before) => {
          if (before && shown.every((id) => before.has(id))) return before;
          return new Set([...(before ?? []), ...shown]);
        });
      },
      { rootMargin: "240px 0px" },
    );
    observer.current = watcher;
    for (const row of rows.current) watcher.observe(row);
    return () => {
      watcher.disconnect();
      observer.current = null;
    };
    // Starts once per page: `seen` only grows after this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);
  const observeRow = useCallback((row: HTMLElement | null) => {
    if (!row) return;
    rows.current.add(row);
    observer.current?.observe(row);
  }, []);
  return { seen, observeRow };
}
