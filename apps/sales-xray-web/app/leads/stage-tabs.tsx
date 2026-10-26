"use client";

/**
 * Leads by stage (owner, 22 Oct 2026: replace the Everyone / Mine / No owner
 * bar with stage tabs, from the organisation's own stages). One strip: To
 * call (the desk), Open, then each kind of stage the business uses, Won,
 * Lost and Junk last, each with its real count. On a phone the strip scrolls inside
 * itself and keeps the chosen tab in view.
 */

import { useLayoutEffect, useRef } from "react";

import type { JourneyView, Kind } from "./journey/journey-client";
import styles from "./leads.module.css";

export type StageTab = { key: string; label: string; count?: number };

/** The order a lead moves in; Won and Lost close it. */
export const KIND_ORDER: Kind[] = [
  "new",
  "not_connected",
  "follow_up",
  "interested",
  "won",
  "lost",
  "junk",
];

const OPEN_KINDS: Kind[] = ["new", "not_connected", "follow_up", "interested"];

/** Plain words for a kind, when a business has several stages of it. */
export const KIND_WORDS: Record<Kind, string> = {
  new: "New",
  not_connected: "Not connected",
  follow_up: "Follow up",
  interested: "Interested",
  won: "Won",
  lost: "Lost",
  junk: "Junk",
};

/**
 * The tabs after To call: Open, then the kinds the business's stages use
 * (all of them when it has no list yet), named by its own stage when only one
 * stage has that kind. Won and Lost are always there. Junk only where the
 * business's list has a Junk stage, or junk leads remain: the sales team's
 * eight stages have none, a lead that was never real being Lost, "Junk / not a
 * real lead" (owner, 26 Oct 2026).
 */
export function stageTabs(
  journey: Pick<JourneyView, "stages"> | null,
  counts: Record<string, number> | null,
): StageTab[] {
  const live = (journey?.stages ?? []).filter((stage) => !stage.archived);
  const junk =
    live.some((stage) => stage.kind === "junk") || (counts?.junk ?? 0) > 0;
  const kinds = (
    live.length
      ? KIND_ORDER.filter(
          (kind) =>
            kind === "won" ||
            kind === "lost" ||
            kind === "junk" ||
            live.some((stage) => stage.kind === kind),
        )
      : KIND_ORDER
  ).filter((kind) => kind !== "junk" || junk);
  const count = (kind: string) => (counts ? (counts[kind] ?? 0) : undefined);
  const open = counts
    ? OPEN_KINDS.reduce((sum, kind) => sum + (counts[kind] ?? 0), 0)
    : undefined;
  return [
    // Every open lead, in every stage (owner, 23 Oct 2026: "All leads").
    { key: "open", label: "All leads", count: open },
    ...kinds.map((kind) => {
      const own = live.filter((stage) => stage.kind === kind);
      return {
        key: kind,
        label: own.length === 1 ? own[0].label : KIND_WORDS[kind],
        count: count(kind),
      };
    }),
  ];
}

export function StageTabs({
  tabs,
  current,
  onChange,
}: {
  tabs: StageTab[];
  current: string;
  onChange: (key: string) => void;
}) {
  const strip = useRef<HTMLDivElement>(null);
  // The chosen tab stays in view, also when the page opens on a later one.
  // Only the strip scrolls: scrollIntoView would also move a clipped
  // ancestor sideways, which reads as the page running off the right edge
  // (production report #28, 26 Oct 2026).
  useLayoutEffect(() => {
    const box = strip.current;
    const chosen = box?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!box || !chosen) return;
    const edge = box.getBoundingClientRect();
    const tab = chosen.getBoundingClientRect();
    // Clear of the 24 px fade on the right, and of the left edge.
    if (tab.right > edge.right - 24)
      box.scrollLeft += tab.right - edge.right + 24;
    else if (tab.left < edge.left) box.scrollLeft -= edge.left - tab.left;
  }, [current]);
  return (
    <div
      ref={strip}
      className={styles.stageTabs}
      role="tablist"
      aria-label="Lead stages"
    >
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          className={styles.stageTab}
          aria-selected={tab.key === current}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
          {tab.count !== undefined ? (
            <span className={styles.stageCount}>{tab.count}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}
