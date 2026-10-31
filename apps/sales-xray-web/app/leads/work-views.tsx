"use client";

/**
 * Leads' work views and stage pick (Dipak's Home + Leads handoff, 31 Oct 2026,
 * items 46-80). To Call, Follow-ups and All Leads are views, not stages, and
 * Follow-ups splits into Due Today, Overdue and Upcoming. One Pipeline stage
 * dropdown names every stage the seller sees, in the organisation's order (no
 * row of nine buttons). Search sits on the page with one Filter beside it.
 *
 * Owner, 31 Oct 2026: one pinned head and nothing scrolling above it; Call
 * Next sits in that head, so it never covers a lead or the tab bar. On a
 * computer the head is one toolbar row with the work views under it, and the
 * selected lead's Prospect's Information sits beside the list.
 */

import { ChevronRight, PhoneCall, Search, X } from "lucide-react";
import {
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { Picker, type PickerOption } from "../ui/picker";
import type { StageView } from "./journey/journey-client";
import { stageName, stageTone, type Side } from "./journey/stage-look";
import {
  moreParams,
  type FollowUpWhen,
  type ListMore,
  type WorkView,
} from "./leads-client";
import styles from "./work-views.module.css";

export const WORK_VIEWS: readonly { key: WorkView; label: string }[] = [
  { key: "to_call", label: "To Call" },
  { key: "follow_ups", label: "Follow-ups" },
  { key: "all", label: "All Leads" },
];

export const FOLLOW_UPS: readonly { key: FollowUpWhen; label: string }[] = [
  { key: "today", label: "Due Today" },
  { key: "overdue", label: "Overdue" },
  { key: "upcoming", label: "Upcoming" },
];

/** The list's own line: what it holds, on which side (items 56-62). */
export function listTitle(
  view: WorkView,
  side: Side,
  when: FollowUpWhen | null,
): string {
  const type = side === "cold" ? "Cold" : "Inbound";
  if (view === "to_call") return `${type} leads to call`;
  if (view === "follow_ups") {
    const part = FOLLOW_UPS.find((item) => item.key === when);
    return part ? `${part.label} · ${type}` : `${type} follow-ups`;
  }
  return `All ${type.toLowerCase()} leads`;
}

/** The last work view (type, view, stage and filters), remembered per person and
 *  workspace on this device; a bare /leads opens it again (owner, 31 Oct 2026:
 *  no saving step). */
const lastViewKey = (person: string) => `sx:leads-last-view:${person}`;

/** Keep the work view (never a lead, a search or whose leads); true when it is
 *  more than where Leads opens. */
export function rememberView(person: string, more: ListMore): boolean {
  const kept = new URLSearchParams(moreParams(more)).toString();
  try {
    if (kept) window.localStorage.setItem(lastViewKey(person), kept);
    else window.localStorage.removeItem(lastViewKey(person));
  } catch {
    // Private browsing keeps nothing; Leads opens on To Call.
  }
  return !!kept;
}

export function lastView(person: string): string | null {
  try {
    return window.localStorage.getItem(lastViewKey(person));
  } catch {
    return null;
  }
}

/** What an empty work view says. */
export function emptyWords(view: WorkView): { title: string; text: string } {
  if (view === "to_call")
    return {
      title: "Nobody to call right now",
      text: "New leads and calls due today show here.",
    };
  if (view === "follow_ups")
    return {
      title: "No follow-ups here",
      text: "A follow-up set after a call shows here, on its day.",
    };
  return {
    title: "No leads yet",
    text: "Add a lead, or connect your ad form in Lead sources.",
  };
}

/**
 * The one pinned head over the list. A phone stacks the lead type, search,
 * the work views and the stage pick with Call Next; a computer puts the type,
 * search, stage pick and Call Next in one toolbar row, the views under it.
 * Its height is shared as --work-head-h, so the lead beside the list pins
 * under it.
 */
export function WorkHead({
  chip = null,
  side = null,
  search,
  stage,
  call = null,
  views,
  split = null,
}: {
  chip?: ReactNode;
  side?: ReactNode;
  search: ReactNode;
  stage: ReactNode;
  call?: ReactNode;
  views: ReactNode;
  split?: ReactNode;
}) {
  const head = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = head.current;
    const holder = node?.parentElement;
    if (!node || !holder || typeof ResizeObserver === "undefined") return;
    const share = () =>
      holder.style.setProperty("--work-head-h", `${node.offsetHeight}px`);
    share();
    const watch = new ResizeObserver(share);
    watch.observe(node);
    return () => watch.disconnect();
  }, []);
  return (
    <div ref={head} className={styles.head}>
      {chip}
      <div className={styles.headTools}>
        {side ? <div className={styles.headSide}>{side}</div> : null}
        {search}
        <div className={styles.headStage}>
          {stage}
          {call}
        </div>
      </div>
      <div className={styles.headViews}>
        {views}
        {split}
      </div>
    </div>
  );
}

const WIDE = "(min-width: 1100px)";
const watchWide = (change: () => void) => {
  const query = window.matchMedia?.(WIDE);
  query?.addEventListener?.("change", change);
  return () => query?.removeEventListener?.("change", change);
};

/** A screen wide enough for the list and the lead side by side. */
export function useWide(): boolean {
  return useSyncExternalStore(
    watchWide,
    () => !!window.matchMedia?.(WIDE).matches,
    () => false,
  );
}

/** The list, and on a wide screen the selected lead beside it. */
export function WorkSplit({
  pane,
  children,
}: {
  pane: ReactNode;
  children: ReactNode;
}) {
  // The lead's pane ends just above the window's bottom wherever it sits: lower
  // at rest, pinned under the head once the page scrolls (owner, 31 Oct 2026:
  // at rest it ran 28 px past the window and half-hid the after-call Save).
  const box = useRef<HTMLDivElement>(null);
  const open = pane !== null && pane !== undefined && pane !== false;
  useLayoutEffect(() => {
    const node = box.current;
    if (!open || !node) return;
    let frame = 0;
    const fit = () => {
      frame = 0;
      const top = Math.max(0, Math.round(node.getBoundingClientRect().top));
      node.style.setProperty("--pane-top", `${top}px`);
    };
    const ask = () => {
      if (!frame) frame = window.requestAnimationFrame(fit);
    };
    fit();
    document.addEventListener("scroll", ask, { passive: true, capture: true });
    window.addEventListener("resize", ask);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("scroll", ask, { capture: true });
      window.removeEventListener("resize", ask);
    };
  }, [open]);
  return (
    <div className={styles.split} data-pane={pane ? "" : undefined}>
      <div className={styles.splitList}>{children}</div>
      {pane ? (
        <div ref={box} className={styles.splitPane}>
          {pane}
        </div>
      ) : null}
    </div>
  );
}

function Tabs<T extends string>({
  label,
  items,
  value,
  onChange,
  small = false,
}: {
  label: string;
  items: readonly { key: T; label: string }[];
  value: T | null;
  onChange: (key: T) => void;
  small?: boolean;
}) {
  return (
    <div
      className={small ? styles.subTabs : styles.tabs}
      role="tablist"
      aria-label={label}
    >
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-selected={item.key === value}
          className={styles.tab}
          onClick={() => {
            if (item.key !== value) onChange(item.key);
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function ViewTabs({
  value,
  onChange,
}: {
  value: WorkView;
  onChange: (view: WorkView) => void;
}) {
  return (
    <Tabs
      label="Work views"
      items={WORK_VIEWS}
      value={value}
      onChange={onChange}
    />
  );
}

export function FollowUpTabs({
  value,
  onChange,
}: {
  value: FollowUpWhen | null;
  onChange: (when: FollowUpWhen) => void;
}) {
  return (
    <Tabs
      label="Follow-ups"
      items={FOLLOW_UPS}
      value={value}
      onChange={onChange}
      small
    />
  );
}

/** The stages a person may pick: sellers see the ones shown to sellers. */
export function pickableStages(
  stages: readonly StageView[] | null | undefined,
  canManage: boolean,
): StageView[] {
  return (stages ?? []).filter(
    (stage) => !stage.archived && (canManage || stage.visible !== false),
  );
}

/** The stage pick: the one picker, each stage with its colour dot and count. */
export function StagePicker({
  stages,
  side,
  value,
  counts = null,
  onChange,
}: {
  stages: readonly StageView[];
  side: Side;
  /** A stage key, or null for All stages. */
  value: string | null;
  /** Each stage's leads for the list's other filters, when the server counts them. */
  counts?: Readonly<Record<string, number>> | null;
  onChange: (key: string | null) => void;
}) {
  const options: PickerOption[] = stages.map((stage) => ({
    key: stage.key,
    label: stageName(stage, side),
    tone: stageTone(stage),
    count: counts ? (counts[stage.key] ?? 0) : null,
  }));
  // A link may name a stage this list does not offer: it still shows.
  if (value && !stages.some((stage) => stage.key === value))
    options.push({ key: value, label: value });
  const total = counts
    ? Object.values(counts).reduce((sum, count) => sum + count, 0)
    : null;
  return (
    <Picker
      className={styles.stage}
      title="Pipeline stage"
      label="Pipeline stage:"
      value={value}
      options={options}
      all={{ label: "All stages", count: total }}
      onChange={onChange}
    />
  );
}

/** Search accessible leads by name, phone or company, with one Filter beside it. */
export function LeadSearch({
  value,
  onChange,
  filter,
}: {
  value: string;
  onChange: (value: string) => void;
  filter: ReactNode;
}) {
  return (
    <div className={styles.searchRow}>
      <label className={styles.search}>
        <Search size={18} aria-hidden="true" className={styles.searchMark} />
        <input
          type="search"
          className={styles.searchInput}
          placeholder="Search name or number"
          aria-label="Search leads"
          value={value}
          enterKeyHint="search"
          onChange={(event) => onChange(event.target.value)}
        />
        {value ? (
          // Clearing the search keeps the filters (item 48).
          <button
            type="button"
            className={styles.searchClear}
            aria-label="Clear search"
            onClick={() => onChange("")}
          >
            <X size={16} aria-hidden="true" />
          </button>
        ) : null}
      </label>
      {filter}
    </div>
  );
}

/** Call Next Lead (Inbound) or Start Cold Calling: the list's first lead. */
export function CallNext({
  side,
  disabled,
  onStart,
}: {
  side: Side;
  disabled: boolean;
  onStart: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.callNextButton}
      disabled={disabled}
      onClick={onStart}
    >
      <PhoneCall size={16} aria-hidden="true" />
      {side === "cold" ? "Start Cold Calling" : "Call Next Lead"}
      <ChevronRight size={16} aria-hidden="true" />
    </button>
  );
}
