"use client";

import {
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  reportSectionAddress,
  reportSectionFromSearch,
} from "./report-navigation";
import styles from "./report-explorer.module.css";

const SECTION_CHANGE = "ac:report-section-change";
function subscribeToNavigation(notify: () => void) {
  window.addEventListener("popstate", notify);
  window.addEventListener(SECTION_CHANGE, notify);
  return () => {
    window.removeEventListener("popstate", notify);
    window.removeEventListener(SECTION_CHANGE, notify);
  };
}
const browserSearch = () => window.location.search;
const serverSearch = () => "";

export type ReportPanel = {
  id: string;
  label: string;
  compactLabel?: string;
  content: ReactNode;
};

/** Section changes preserve mounted search, measurement and audio state. */
export function ReportExplorer({
  label,
  panels,
  boundCallId,
}: {
  label: string;
  panels: ReportPanel[];
  /** Supplied only after the report and its owner/source binding are validated. */
  boundCallId?: string;
}) {
  const prefix = useId();
  const [selected, setSelected] = useState(panels[0]?.id);
  const search = useSyncExternalStore(
    subscribeToNavigation,
    browserSearch,
    serverSearch,
  );
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const requested = boundCallId
    ? reportSectionFromSearch(search, boundCallId)
    : selected;
  const active = panels.some((panel) => panel.id === requested)
    ? requested
    : panels[0]?.id;
  const select = (section: string) => {
    if (boundCallId) {
      const address = reportSectionAddress(
        new URL(window.location.href),
        boundCallId,
        section,
      );
      if (!address) return;
      const current =
        window.location.pathname +
        window.location.search +
        window.location.hash;
      if (address !== current) {
        // A report section is a bookmarkable view of this call, not a new
        // browser destination. Keep Back pointed at the page that opened it.
        window.history.replaceState(null, "", address);
        window.dispatchEvent(new Event(SECTION_CHANGE));
      }
    } else setSelected(section);
  };
  if (!panels.length) return null;

  return (
    <div className={styles.explorer} data-report-section={active}>
      <div className={styles.tabs} role="tablist" aria-label={label}>
        {panels.map((panel, index) => (
          <button
            key={panel.id}
            ref={(button) => {
              buttons.current[index] = button;
            }}
            type="button"
            role="tab"
            aria-label={
              panel.compactLabel
                ? panel.label
                    .toLowerCase()
                    .includes(panel.compactLabel.toLowerCase())
                  ? panel.label
                  : `${panel.label} (${panel.compactLabel})`
                : undefined
            }
            id={`${prefix}-tab-${panel.id}`}
            aria-controls={`${prefix}-panel-${panel.id}`}
            aria-selected={active === panel.id}
            tabIndex={active === panel.id ? 0 : -1}
            onClick={() => select(panel.id)}
            onKeyDown={(event) => {
              let next: number;
              if (event.key === "ArrowRight")
                next = (index + 1) % panels.length;
              else if (event.key === "ArrowLeft")
                next = (index + panels.length - 1) % panels.length;
              else if (event.key === "Home") next = 0;
              else if (event.key === "End") next = panels.length - 1;
              else return;
              event.preventDefault();
              select(panels[next].id);
              buttons.current[next]?.focus();
            }}
          >
            {panel.compactLabel ? (
              <>
                <span className={styles.fullLabel}>{panel.label}</span>
                <span className={styles.compactLabel}>
                  {panel.compactLabel}
                </span>
              </>
            ) : (
              panel.label
            )}
          </button>
        ))}
      </div>
      {panels.map((panel) => (
        <div
          key={panel.id}
          id={`${prefix}-panel-${panel.id}`}
          className={styles.panel}
          role="tabpanel"
          aria-labelledby={`${prefix}-tab-${panel.id}`}
          hidden={active !== panel.id}
          tabIndex={0}
        >
          {panel.content}
        </div>
      ))}
    </div>
  );
}
