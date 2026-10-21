"use client";

/**
 * Leads by stage (owner, 22 Oct 2026: replace the Everyone / Mine / No owner
 * bar with stage tabs, from the organisation's own stages). One strip: To
 * call (the desk), Open, then each kind of stage the business uses, Won and
 * Lost last, each with its real count. On a phone the strip scrolls inside
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
];

const OPEN_KINDS: Kind[] = ["new", "not_connected", "follow_up", "interested"];

/** Plain words for a kind, when a business has several stages of it. */
export const KIND_WORDS: Record<Kind, string> = {
  new: "New",
  not_connected: "Not contacted",
  follow_up: "Follow up",
  interested: "Interested",
  won: "Won",
  lost: "Lost",
};

/**
 * The tabs after To call: Open, then the kinds the business's stages use
 * (all six when it has no list yet), named by its own stage when only one
 * stage has that kind. Won and Lost are always there.
 */
export function stageTabs(
  journey: Pick<JourneyView, "stages"> | null,
  counts: Record<string, number> | null,
): StageTab[] {
  const live = (journey?.stages ?? []).filter((stage) => !stage.archived);
  const kinds = live.length
    ? KIND_ORDER.filter(
        (kind) =>
          kind === "won" ||
          kind === "lost" ||
          live.some((stage) => stage.kind === kind),
      )
    : KIND_ORDER;
  const count = (kind: string) => (counts ? (counts[kind] ?? 0) : undefined);
  const open = counts
    ? OPEN_KINDS.reduce((sum, kind) => sum + (counts[kind] ?? 0), 0)
    : undefined;
  return [
    { key: "open", label: "Open", count: open },
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
  useLayoutEffect(() => {
    const chosen = strip.current?.querySelector<HTMLElement>(
      '[aria-selected="true"]',
    );
    chosen?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
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
