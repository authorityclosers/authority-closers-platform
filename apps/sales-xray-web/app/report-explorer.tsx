"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import styles from "./report-explorer.module.css";

export type ReportPanel = { id: string; label: string; content: ReactNode };

/** Section changes preserve mounted search, measurement and audio state. */
export function ReportExplorer({
  label,
  panels,
}: {
  label: string;
  panels: ReportPanel[];
}) {
  const prefix = useId();
  const [selected, setSelected] = useState(panels[0]?.id);
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const active = panels.some((panel) => panel.id === selected)
    ? selected
    : panels[0]?.id;
  if (!panels.length) return null;

  return (
    <div className={styles.explorer}>
      <div className={styles.tabs} role="tablist" aria-label={label}>
        {panels.map((panel, index) => (
          <button
            key={panel.id}
            ref={(button) => {
              buttons.current[index] = button;
            }}
            type="button"
            role="tab"
            id={`${prefix}-tab-${panel.id}`}
            aria-controls={`${prefix}-panel-${panel.id}`}
            aria-selected={active === panel.id}
            tabIndex={active === panel.id ? 0 : -1}
            onClick={() => setSelected(panel.id)}
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
              setSelected(panels[next].id);
              buttons.current[next]?.focus();
            }}
          >
            {panel.label}
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
