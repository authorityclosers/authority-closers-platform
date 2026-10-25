"use client";

/**
 * Leads' views in one switch (owner, 25 Oct 2026: "My work / Board / To call /
 * All leads: it's unclear what to focus on"). Now comes first (who to call now),
 * All leads beside it, and the other views wait under More, in a sheet. Three
 * equal segments, 44 px tall, the same on every view; a view's own tools (Filter,
 * the stage chips, To call's pipeline) sit in the row under it.
 */

import {
  ChevronDown,
  Columns3,
  History,
  ListChecks,
  StickyNote,
} from "lucide-react";
import type { ReactNode } from "react";

import { haptic } from "../ui/haptics";
import { ActionList, ActionRow } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import styles from "./view-switch.module.css";

export type Section = "now" | "all" | "more";
export type MoreView = { key: string; label: string; note: string };

const ICONS: Record<string, ReactNode> = {
  board: <Columns3 size={20} />,
  work: <History size={20} />,
  tasks: <ListChecks size={20} />,
  notes: <StickyNote size={20} />,
};

function Count({ value }: { value: number | undefined }) {
  return value === undefined ? null : (
    <span className={styles.count}>{value}</span>
  );
}

export function ViewSwitch({
  section,
  nowCount,
  allCount,
  moreLabel,
  onNow,
  onAll,
  onMore,
}: {
  section: Section;
  nowCount?: number;
  allCount?: number;
  /** "More", or the chosen view's name while one of them is open. */
  moreLabel: string;
  onNow: () => void;
  onAll: () => void;
  onMore: () => void;
}) {
  return (
    <nav className={styles.switch} aria-label="Leads views">
      <button
        type="button"
        className={styles.segment}
        aria-current={section === "now" ? "page" : undefined}
        onClick={() => {
          haptic("tap");
          onNow();
        }}
      >
        <span className={styles.label}>Now</span>
        <Count value={nowCount} />
      </button>
      <button
        type="button"
        className={styles.segment}
        aria-current={section === "all" ? "page" : undefined}
        onClick={() => {
          haptic("tap");
          onAll();
        }}
      >
        <span className={styles.label}>All leads</span>
        <Count value={allCount} />
      </button>
      <button
        type="button"
        className={styles.segment}
        aria-current={section === "more" ? "page" : undefined}
        aria-haspopup="dialog"
        onClick={() => {
          haptic("tap");
          onMore();
        }}
      >
        <span className={styles.label}>{moreLabel}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
    </nav>
  );
}

/** The row under the switch: the open view's own tools, or nothing. */
export function ViewTools({ children }: { children: ReactNode }) {
  return <div className={styles.tools}>{children}</div>;
}

export function MoreViews({
  open,
  onClose,
  views,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  views: MoreView[];
  onPick: (key: string) => void;
}) {
  return (
    <Sheet open={open} onClose={onClose} title="More views" wide="center">
      <ActionList label="More views">
        {views.map((view) => (
          <ActionRow
            key={view.key}
            icon={ICONS[view.key]}
            title={view.label}
            note={view.note}
            onClick={() => {
              onClose();
              onPick(view.key);
            }}
          />
        ))}
      </ActionList>
    </Sheet>
  );
}
