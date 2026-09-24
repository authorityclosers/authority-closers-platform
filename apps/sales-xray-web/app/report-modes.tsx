"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { ReportReadingProvider } from "./report-reading-context";
import styles from "./report-modes.module.css";

export type ReportPanel = {
  id: string;
  label: string;
  compactLabel?: string;
  content: ReactNode;
};

type View = "reading" | "tabs";
type Address = { view: View; section: string };
const CHANGE = "ac:report-mode-change";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  window.addEventListener(CHANGE, notify);
  return () => {
    window.removeEventListener("popstate", notify);
    window.removeEventListener(CHANGE, notify);
  };
}

function addressFromSearch(
  search: string,
  boundCallId: string,
  panels: ReportPanel[],
): Address | null {
  const query = new URLSearchParams(search);
  const calls = query.getAll("call");
  if (!UUID.test(boundCallId) || calls.length !== 1 || calls[0] !== boundCallId)
    return null;
  const views = query.getAll("view");
  const sections = query.getAll("section");
  const view =
    views.length === 1 && (views[0] === "reading" || views[0] === "tabs")
      ? views[0]
      : "reading";
  const section =
    sections.length === 1 && panels.some((panel) => panel.id === sections[0])
      ? sections[0]
      : panels[0]?.id;
  return section ? { view, section } : null;
}

function browserSearch() {
  return window.location.search;
}

function serverSearch() {
  return "";
}

/** Keeps every report section mounted while switching between continuous reading and tabs. */
export function ReportModes({
  label = "Report sections",
  panels,
  boundCallId,
}: {
  label?: string;
  panels: ReportPanel[];
  /** Enables bookmarkable view and section state for this already-bound report. */
  boundCallId?: string;
}) {
  const id = useId();
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const [local, setLocal] = useState<Address>({
    view: "reading",
    section: panels[0]?.id ?? "",
  });
  const [readingSection, setReadingSection] = useState(panels[0]?.id ?? "");
  const search = useSyncExternalStore(subscribe, browserSearch, serverSearch);

  const linked = boundCallId
    ? addressFromSearch(search, boundCallId, panels)
    : null;
  const address = linked ?? local;
  const view = address.view;
  const selected = panels.some((panel) => panel.id === address.section)
    ? address.section
    : panels[0]?.id;
  const currentReadingSection = panels.some(
    (panel) => panel.id === readingSection,
  )
    ? readingSection
    : selected;

  useEffect(() => {
    if (view !== "reading" || !selected) return;
    const update = () => {
      const readingLine = Math.min(180, window.innerHeight * 0.4);
      let current = panels[0]?.id ?? "";
      for (const panel of panels) {
        const heading = document.getElementById(`${id}-heading-${panel.id}`);
        const bounds = heading?.getBoundingClientRect();
        if (bounds && bounds.height > 0 && bounds.top <= readingLine)
          current = panel.id;
      }
      setReadingSection((previous) =>
        previous === current ? previous : current,
      );
    };
    update();
    document.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      document.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [id, panels, selected, view]);

  useEffect(() => {
    if (
      linked?.view !== "reading" ||
      !new URLSearchParams(search).has("section")
    )
      return;
    setReadingSection(linked.section);
    const frame = requestAnimationFrame(() => {
      document
        .getElementById(`${id}-heading-${linked.section}`)
        ?.scrollIntoView?.({ block: "start" });
    });
    return () => cancelAnimationFrame(frame);
  }, [id, linked?.section, linked?.view, search]);

  if (!panels.length) return null;

  function navigate(next: Address, focus = false) {
    if (boundCallId) {
      if (!UUID.test(boundCallId)) return;
      const current = new URL(window.location.href);
      const calls = current.searchParams.getAll("call");
      if (calls.length > 1 || (calls.length === 1 && calls[0] !== boundCallId))
        return;
      current.searchParams.set("call", boundCallId);
      current.searchParams.delete("new");
      current.searchParams.set("view", next.view);
      current.searchParams.set("section", next.section);
      const target = `${current.pathname}?${current.searchParams.toString()}${current.hash}`;
      const here = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      if (target !== here)
        window.history.replaceState(window.history.state, "", target);
      window.dispatchEvent(new Event(CHANGE));
    } else setLocal(next);
    setReadingSection(next.section);
    if (focus) {
      requestAnimationFrame(() => {
        const index = panels.findIndex((panel) => panel.id === next.section);
        if (next.view === "tabs")
          buttons.current[index]?.focus({ preventScroll: true });
        else {
          const heading = document.getElementById(
            `${id}-heading-${next.section}`,
          );
          heading?.focus({ preventScroll: true });
          heading?.scrollIntoView?.({ block: "start" });
        }
      });
    }
  }

  return (
    <div
      className={styles.workspace}
      data-report-modes
      data-view={view}
      data-report-section={
        view === "reading" ? currentReadingSection : selected
      }
    >
      <div className={styles.toolbar} role="group" aria-label={`${label} view`}>
        <button
          type="button"
          aria-pressed={view === "reading"}
          onClick={() => navigate({ view: "reading", section: selected })}
        >
          Reading view
        </button>
        <button
          type="button"
          aria-pressed={view === "tabs"}
          onClick={() =>
            navigate({ view: "tabs", section: currentReadingSection })
          }
        >
          Tabbed view
        </button>
      </div>

      {view === "tabs" && (
        <div className={styles.tabs} role="tablist" aria-label={label}>
          {panels.map((panel, index) => (
            <button
              key={panel.id}
              ref={(element) => {
                buttons.current[index] = element;
              }}
              type="button"
              role="tab"
              id={`${id}-tab-${panel.id}`}
              aria-controls={`${id}-section-${panel.id}`}
              aria-selected={selected === panel.id}
              tabIndex={selected === panel.id ? 0 : -1}
              onClick={() => navigate({ view, section: panel.id })}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % panels.length
                    : event.key === "ArrowLeft"
                      ? (index + panels.length - 1) % panels.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? panels.length - 1
                          : null;
                if (next === null) return;
                event.preventDefault();
                navigate({ view, section: panels[next].id });
                buttons.current[next]?.focus();
              }}
            >
              {panel.label}
            </button>
          ))}
        </div>
      )}

      <div className={styles.layout}>
        {view === "reading" && (
          <nav className={styles.contents} aria-label={label}>
            {panels.map((panel) => (
              <a
                key={panel.id}
                href={
                  boundCallId
                    ? `?call=${encodeURIComponent(boundCallId)}&view=reading&section=${encodeURIComponent(panel.id)}`
                    : `#${id}-section-${panel.id}`
                }
                aria-current={
                  currentReadingSection === panel.id ? "location" : undefined
                }
                onClick={(event) => {
                  if (
                    event.metaKey ||
                    event.ctrlKey ||
                    event.shiftKey ||
                    event.altKey
                  )
                    return;
                  event.preventDefault();
                  navigate({ view, section: panel.id }, true);
                }}
              >
                {panel.label}
              </a>
            ))}
          </nav>
        )}

        <ReportReadingProvider reading={view === "reading"}>
          <div className={styles.sections}>
            {panels.map((panel) => (
              <section
                key={panel.id}
                id={`${id}-section-${panel.id}`}
                className={styles.section}
                data-report-mode-section={panel.id}
                role={view === "tabs" ? "tabpanel" : "region"}
                aria-labelledby={
                  view === "tabs"
                    ? `${id}-tab-${panel.id}`
                    : `${id}-heading-${panel.id}`
                }
                hidden={view === "tabs" && selected !== panel.id}
                tabIndex={view === "tabs" ? 0 : -1}
              >
                <h2 id={`${id}-heading-${panel.id}`} tabIndex={-1}>
                  {panel.label}
                </h2>
                {panel.content}
              </section>
            ))}
          </div>
        </ReportReadingProvider>
      </div>
    </div>
  );
}
