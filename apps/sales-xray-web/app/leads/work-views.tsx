"use client";

/**
 * Leads' work views and stage pick (Dipak's Home + Leads handoff, 31 Oct 2026,
 * items 46-80). To Call, Follow-ups and All Leads are views, not stages, and
 * Follow-ups splits into Due Today, Overdue and Upcoming. One Pipeline stage
 * dropdown names every stage the seller sees, in the organisation's order (no
 * row of nine buttons). Search sits on the page with one Filter beside it.
 *
 * Leads L1 (the owner's pick, 8 Nov 2026: "Build L1"; docs/design/screens/
 * leads/spec.md): Inbound | Cold as Home has it, then pinned the work views as
 * text tabs with their counts and one row of stage chips, counted in the view,
 * with Filter at its end. Search is the app bar's; Call Next is one band above
 * the tab bar, never over a row. On a computer the list column has the same
 * stack, and the selected lead's Prospect's Information sits beside it.
 */

import {
  ChevronRight,
  PhoneCall,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { ChipRow, CountTabs } from "@ac/ui/kit";

import lens from "../ui/call-lens/call-lens.module.css";
import { haptic } from "../ui/haptics";
import { Picker, type PickerOption } from "../ui/picker";
import { can as roleCan } from "../organisation/roles";
import { MAIN_PIPELINE, type StageView } from "./journey/journey-client";
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
  // Every lead on both sides (owner, 2 Nov 2026: "All leads" lists every lead).
  return "All leads";
}

/** A row's stage on All Leads, which lists both sides: a Cold lead says so
 *  ("Cold · Unworked"); an Inbound one reads as before. */
export function sideStage(
  row: { side?: "inbound" | "cold" },
  stage: string,
): string {
  return row.side === "cold" ? `Cold · ${stage}` : stage;
}

/** The last work view (type, view, stage and filters), remembered per person and
 *  workspace on this device; a bare /leads opens it again (owner, 31 Oct 2026:
 *  no saving step). */
const lastViewKey = (person: string) => `sx:leads-last-view:${person}`;

/** Keep the work view (never a lead, a search or whose leads); true when it is
 *  more than where Leads opens. */
/** Whether the list on screen is kept as the person's last view: never the
 *  one Leads was opened with from elsewhere (a Home tile, a link), only what
 *  they pick here (Redmi QA, 10 Nov 2026: a Home New leads tile's filter was
 *  still on Leads hours later). `arrival`: the list the address opened with. */
export function keepsView(more: ListMore, arrival: ListMore | null): boolean {
  if (!arrival) return true;
  const words = (value: ListMore) =>
    new URLSearchParams(moreParams(value)).toString();
  const opened = words(arrival);
  return !opened || words(more) !== opened;
}

/** Why the list isn't here: offline, it says so and that it comes back by
 *  itself (Redmi QA, 10 Nov 2026: offline, "Sales X-Ray isn't answering. Try
 *  again." and no word that the network was the cause). */
export function notLoadedText(message: string, online: boolean): string {
  return online
    ? message
    : "You're offline. They load by themselves once you're back online.";
}

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
 * The head over the list (Leads L1). Inbound | Cold sits above it and scrolls
 * away; pinned are the work views (text tabs with their counts) and the stage
 * chips with Filter at their end. Search shows here only while one is on, so it
 * can be cleared (the app bar's search finds leads). Its height is shared as
 * --work-head-h, so the lead beside the list pins under it.
 */
export function WorkHead({
  chip = null,
  side = null,
  search = null,
  stage,
  views,
  syncSlot,
}: {
  chip?: ReactNode;
  side?: ReactNode;
  search?: ReactNode;
  stage: ReactNode;
  views: ReactNode;
  /** The list's "Syncing…" sign is drawn here, at the head's lower edge, so
   *  it takes no room in the list (a 48 px head that came and went moved the
   *  rows on every load: QA robot 22a02493, 8 Nov 2026). */
  syncSlot?: (node: HTMLElement | null) => void;
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
    <>
      {side ? <div className={styles.headSide}>{side}</div> : null}
      <div ref={head} className={styles.head}>
        {chip}
        {search}
        {views}
        <div className={styles.headStage}>{stage}</div>
        {syncSlot ? <span ref={syncSlot} className={styles.headSync} /> : null}
      </div>
    </>
  );
}

/** The element the page scrolls in: the app's own content area, or the window. */
function scrollerOf(node: HTMLElement): Element {
  for (let at = node.parentElement; at; at = at.parentElement) {
    const flow = getComputedStyle(at).overflowY;
    if (
      (flow === "auto" || flow === "scroll") &&
      at.scrollHeight > at.clientHeight
    )
      return at;
  }
  return document.scrollingElement ?? document.documentElement;
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
      // The room under the list's end (the page's own foot, and the window
      // below its scroller): the pane leaves it free, so at the list's end it
      // is never lifted under the pinned head (QA robot 898f3d7a, 3 Nov 2026:
      // at 1440 Close sat under Call Next).
      const split = node.parentElement;
      const scroller = scrollerOf(node);
      if (!split) return;
      const view =
        scroller === document.scrollingElement
          ? { top: 0, bottom: window.innerHeight }
          : scroller.getBoundingClientRect();
      const end =
        split.getBoundingClientRect().bottom - view.top + scroller.scrollTop;
      const after =
        Math.max(0, scroller.scrollHeight - end) +
        Math.max(0, window.innerHeight - view.bottom);
      node.style.setProperty("--split-after", `${Math.round(after)}px`);
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

/** A tab's count, short enough for a phone: 7, 999, 1.2K, 1.2L. */
export function tabCount(count: number): string {
  return count < 1000
    ? String(count)
    : new Intl.NumberFormat("en-IN", {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(count);
}

function Tabs<T extends string>({
  label,
  items,
  value,
  onChange,
  small = false,
  counts = null,
  onClear,
}: {
  label: string;
  items: readonly { key: T; label: string }[];
  value: T | null;
  onChange: (key: T) => void;
  /** Tapping the chosen tab again clears it (Follow-ups' split). */
  onClear?: () => void;
  small?: boolean;
  /** Each tab's count, when the list has counted them. */
  counts?: Partial<Record<T, number>> | null;
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
            else onClear?.();
          }}
        >
          <span className={styles.tabWord}>{item.label}</span>
          {typeof counts?.[item.key] === "number" ? (
            <>
              {" "}
              <span className={styles.tabCount}>
                {tabCount(counts[item.key] as number)}
              </span>
            </>
          ) : null}
        </button>
      ))}
    </div>
  );
}

/** To Call, Follow-ups and All Leads, each with its count once the list has one
 *  ("To Call 7"): Inbound To Call is the Leads badge's own number (competitor
 *  teardown #9, one count rule). Text tabs on one line that scroll sideways
 *  where they don't fit, never wrapping (Leads L1; bugs 165, 180, ux-audit N7). */
export function ViewTabs({
  value,
  onChange,
  counts = null,
}: {
  value: WorkView;
  onChange: (view: WorkView) => void;
  counts?: Partial<Record<WorkView, number>> | null;
}) {
  return (
    <CountTabs
      label="Work views"
      items={WORK_VIEWS.map((view) => ({
        ...view,
        count: counts?.[view.key] ?? null,
      }))}
      value={value}
      onChange={onChange}
      format={tabCount}
    />
  );
}

/** Due Today, Overdue and Upcoming over every follow-up: none chosen lists them
 *  all, so the tab's count is its rows (owner, 2 Nov 2026); tapping the chosen one
 *  again goes back to all. */
export function FollowUpTabs({
  value,
  onChange,
}: {
  value: FollowUpWhen | null;
  onChange: (when: FollowUpWhen | null) => void;
}) {
  return (
    <Tabs
      label="Follow-ups"
      items={FOLLOW_UPS}
      value={value}
      onChange={onChange}
      onClear={() => onChange(null)}
      small
    />
  );
}

/** Whose stages the stage pick lists: the pipeline picked, else the main one,
 *  which the list counts and filters "All pipelines" by (Dipak, 3 Nov 2026: with
 *  several pipelines and none picked, "All stages" was the only row). */
export function stagesPipeline(picked: string | null | undefined): string {
  return picked || MAIN_PIPELINE;
}

/** The pipelines a person may pick from: none for a seller, who always sees
 *  every pipeline on the main stages (orchestrator, 3 Nov 2026, bug 129); all
 *  of them for whoever manages leads, inside Filter. */
export function pipelinesFor<T>(
  role: string | null | undefined,
  pipes: T | null,
): T | null {
  return roleCan(role, "leads.manage") ? pipes : null;
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

/** Stage keys a link may bring from another list, and the kind each means. */
const MEANS: Readonly<Record<string, string>> = {
  new_lead: "new",
  unworked: "new",
  open_leads: "follow_up",
  discussion_incomplete: "follow_up",
};

/**
 * The stage a link means in this organisation's list (phone personas, 1 Nov
 * 2026: Home's Open Leads opened "open_leads" in a list without one): the stage
 * itself, else the first live stage of the same kind, else null (all stages).
 */
export function resolveStep(
  stages: readonly StageView[],
  key: string,
): string | null {
  const live = stages.filter((stage) => !stage.archived);
  if (live.some((stage) => stage.key === key)) return key;
  const kind = MEANS[key] ?? key;
  return live.find((stage) => stage.kind === kind)?.key ?? null;
}

/** A key in words, never as it is: "demo_done" reads "Demo done". */
const keyWords = (key: string) => {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/** Every stage, each with its colour dot and count; a stage a link names that
 *  this list does not offer still shows. */
function stageOptions(
  stages: readonly StageView[],
  side: Side,
  value: string | null,
  counts: Readonly<Record<string, number>> | null,
): PickerOption[] {
  const options: PickerOption[] = stages.map((stage) => ({
    key: stage.key,
    label: stageName(stage, side),
    tone: stageTone(stage),
    count: counts ? (counts[stage.key] ?? 0) : null,
  }));
  if (value && !stages.some((stage) => stage.key === value))
    options.push({ key: value, label: keyWords(value) });
  return options;
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
  const options = stageOptions(stages, side, value, counts);
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

const ALL_STAGES = "all-stages";

/**
 * The stage pick as one row of chips (Leads L1): "All stages 128", then each
 * stage holding leads in this view, every count the view's own, so they add
 * up to the tab's count (the server's step counts: the same people, filters,
 * view and side, before the stage pick). A stage with none in the view is left
 * out, except the one chosen; until the counts are in, only All stages and the
 * chosen one show. Filter is pinned at the row's end. All stages opens the list
 * of every stage, its chevron saying so (owner bug 193, 9 Nov 2026: "clicking on
 * this can open up a down popup which has listed all the real stages", with "a
 * slight indication of maybe there's a drop-down").
 */
export function StageChips({
  stages,
  side,
  value,
  counts = null,
  onChange,
  end = null,
}: {
  stages: readonly StageView[];
  side: Side;
  /** A stage key, or null for All stages. */
  value: string | null;
  /** Each stage's leads in this view, when the server counts them. */
  counts?: Readonly<Record<string, number>> | null;
  onChange: (key: string | null) => void;
  end?: ReactNode;
}) {
  const total = counts
    ? Object.values(counts).reduce((sum, count) => sum + count, 0)
    : null;
  const items = [
    ...stages
      .filter(
        (stage) =>
          stage.key === value ||
          (counts !== null && (counts[stage.key] ?? 0) > 0),
      )
      .map((stage) => ({
        key: stage.key,
        label: stageName(stage, side),
        count: counts ? (counts[stage.key] ?? 0) : null,
      })),
  ];
  // A link may name a stage this list does not offer: it still shows.
  if (value && !stages.some((stage) => stage.key === value))
    items.push({ key: value, label: keyWords(value), count: null });
  return (
    <ChipRow
      label="Pipeline stage"
      items={items}
      value={value ?? ALL_STAGES}
      onChange={(key) => onChange(key === ALL_STAGES ? null : key)}
      start={
        <Picker
          variant="chip"
          title="Pipeline stage"
          value={value}
          options={stageOptions(stages, side, value, counts)}
          all={{ label: "All stages", count: total }}
          onChange={onChange}
          display={
            <span>
              All stages
              {total !== null ? (
                <>
                  {" "}
                  <span className={styles.stageCount}>{tabCount(total)}</span>
                </>
              ) : null}
            </span>
          }
        />
      }
      end={end}
      format={tabCount}
    />
  );
}

/** Filter at the chip row's end (Leads L1): a 40 dp circle, 48 dp to a finger,
 *  with a dot while a filter other than the stage is on. */
export function FilterButton({
  count,
  onOpen,
}: {
  /** Filters on, other than the stage. */
  count: number;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.filterButton}
      aria-label={count ? `Filter leads, ${count} on` : "Filter leads"}
      aria-haspopup="dialog"
      data-on={count ? "" : undefined}
      onClick={onOpen}
    >
      <SlidersHorizontal size={20} aria-hidden="true" />
    </button>
  );
}

/**
 * Call Next Lead (Inbound) or Start Cold Calling as the screen's one Call
 * (Leads L1): Home's Call, its look and press, in a band docked above the tab
 * bar on a phone and at the list's foot on a computer, so it never covers a
 * row; the list ends above it.
 */
export function CallBand({
  side,
  view = "to_call",
  disabled,
  onStart,
  count = null,
  label = null,
  className,
}: {
  side: Side;
  /** Follow-ups says so: "Call Next Follow-up · 12" (spec §3). */
  view?: WorkView;
  disabled: boolean;
  onStart: () => void;
  /** How many the round would take: "Start Cold Calling · 900". */
  count?: number | null;
  /** Its own words in place of the list's: Home's "Call Asha" (the owner's
   *  pick, 13 Nov 2026: "Call band above tab bar"). */
  label?: string | null;
  /** The page's own class beside the band's (Home keeps it to phones). */
  className?: string;
}) {
  return (
    <div
      className={
        className ? `${styles.callBand} ${className}` : styles.callBand
      }
      data-call-band=""
    >
      <button
        type="button"
        className={`${lens.capsule} ${styles.callBandButton}`}
        disabled={disabled}
        onClick={() => {
          haptic("tap");
          onStart();
        }}
      >
        <PhoneCall
          className={lens.glyph}
          size={20}
          strokeWidth={2}
          aria-hidden="true"
        />
        <span>
          {label ??
            `${
              view === "follow_ups"
                ? "Call Next Follow-up"
                : side === "cold"
                  ? "Start Cold Calling"
                  : "Call Next Lead"
            }${count ? ` · ${tabCount(count)}` : ""}`}
        </span>
      </button>
    </div>
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

/** The list Call Next goes through: the tab's own, but All Leads lists both
 *  sides, so there it is the side's To Call, its count and its leads (phone
 *  QA, 3 Nov 2026: Inbound's All Leads said "Call Next Lead · 913", Cold's). */
export function callNextView(view: WorkView): Exclude<WorkView, "all"> {
  return view === "all" ? "to_call" : view;
}

/** Call Next Lead (Inbound) or Start Cold Calling: the list's first lead. */
export function CallNext({
  side,
  disabled,
  onStart,
  count = null,
}: {
  side: Side;
  disabled: boolean;
  onStart: () => void;
  /** How many the round would take: "Start Cold Calling · 900". */
  count?: number | null;
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
      {count ? (
        <span className={styles.callNextCount}>{` · ${tabCount(count)}`}</span>
      ) : null}
      <ChevronRight size={16} aria-hidden="true" />
    </button>
  );
}
