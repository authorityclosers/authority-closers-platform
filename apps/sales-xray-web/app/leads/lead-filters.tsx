"use client";

/**
 * Leads → Filter (Leads header, agreed with Liquid Glass, 22 Oct 2026): one chip
 * on the header row says how many filters are on; its sheet holds the name or
 * number, whose leads and the pipeline, applied together. Filters that are on
 * show as removable chips under the row. The header's own search (every screen)
 * finds anything; this only narrows the list.
 *
 * Owner, 24 Oct 2026 ("we can't actually access ... filters and sorting both on
 * mobile as well as PC"): the sheet also filters by the next follow-up, the last
 * contact, when the lead came in and its source, and sorts the whole list, all
 * answered by the server.
 */

import { ChevronDown, SlidersHorizontal, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import type {
  FollowUpWhen,
  ListDue,
  ListMade,
  ListMore,
  ListSince,
  ListSort,
} from "./leads-client";
import type { Scope } from "./list-view";
import { Picker } from "../ui/picker";
import styles from "./leads.module.css";

export type LeadFilters = {
  who: Scope;
  pipeline: string | null;
  q: string;
  /** Sort and the other filters, over the whole list. */
  more?: ListMore;
};

type Pipe = { key: string; name: string };

const WHO: { key: Scope; label: string }[] = [
  { key: "team", label: "Everyone" },
  { key: "mine", label: "Mine" },
  { key: "unassigned", label: "No owner" },
];

export const DUE_WORDS: Record<ListDue, string> = {
  late: "Late",
  today: "Due today",
  week: "Due this week",
  none: "No next step",
};
export const WHEN_WORDS: Record<FollowUpWhen, string> = {
  today: "Today",
  overdue: "Overdue",
  upcoming: "Upcoming",
};
export const SINCE_WORDS: Record<ListSince, string> = {
  today: "Talked today",
  week: "Talked this week",
  month: "Talked this month",
  never: "Never talked",
};
export const MADE_WORDS: Record<ListMade, string> = {
  today: "Came in today",
  week: "Came in this week",
  month: "Came in this month",
};
export const SORT_WORDS: Record<ListSort, string> = {
  next_action: "Next follow-up",
  last_contact: "Last contact",
  name: "Name",
  created: "Newest first",
};
/** Oldest first: the newest-first order, reversed (owner, 31 Oct 2026). */
const OLDEST = "oldest";
const SORT_CHOICES: Record<ListSort | typeof OLDEST, string> = {
  ...SORT_WORDS,
  [OLDEST]: "Oldest first",
};

/** The sort as a filter's words. */
function sortLabel(more: ListMore): string {
  if (!more.sort) return "";
  if (more.sort === "created")
    return more.order === "asc" ? "Oldest first" : "Newest first";
  return `By ${SORT_WORDS[more.sort].toLowerCase()}${more.order === "desc" ? ", reversed" : ""}`;
}
/** Where leads come from, in the page's words (the lead's source key). */
export const SOURCE_WORDS: Record<string, string> = {
  meta: "Meta lead form",
  webhook: "Website form",
  sheet: "Google Sheet",
  csv: "File upload",
  manual: "Added by hand",
  referral: "Referral",
};

/** How many filters narrow the list (whose leads counts when it isn't the default;
 *  a sort doesn't narrow it). */
export function filtersOn(filters: LeadFilters, defaultWho: Scope): number {
  const more = filters.more ?? {};
  return (
    (filters.q.trim() ? 1 : 0) +
    (filters.who !== defaultWho ? 1 : 0) +
    (filters.pipeline ? 1 : 0) +
    (more.source ? 1 : 0) +
    (more.due ? 1 : 0) +
    (more.when && more.view !== "follow_ups" ? 1 : 0) +
    (more.contact ? 1 : 0) +
    (more.created ? 1 : 0)
  );
}

/** The sort and filters in a few words, for a saved view's name and its line. */
export function moreWords(more: ListMore | undefined): string[] {
  if (!more) return [];
  return [
    more.due ? DUE_WORDS[more.due] : null,
    more.contact ? SINCE_WORDS[more.contact] : null,
    more.created ? MADE_WORDS[more.created] : null,
    more.source ? (SOURCE_WORDS[more.source] ?? more.source) : null,
    more.sort ? sortLabel(more) : null,
  ].filter((word): word is string => !!word);
}

export function FilterChip({
  count,
  onOpen,
}: {
  count: number;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.statusChip}
      data-on={count ? "" : undefined}
      aria-haspopup="dialog"
      aria-label={count ? `Filter leads, ${count} on` : "Filter leads"}
      onClick={onOpen}
    >
      <SlidersHorizontal size={14} aria-hidden="true" />
      <span className={styles.filterWords}>Filter</span>
      {count ? (
        <span className={styles.filterCount} aria-hidden="true">
          {count}
        </span>
      ) : null}
    </button>
  );
}

/** The filters that are on, each in its chip's words and with what clearing it leaves. */
function filterChips(
  filters: LeadFilters,
  defaultWho: Scope,
  pipes: Pipe[],
): { key: string; label: string; clear: LeadFilters }[] {
  const more = filters.more ?? {};
  const without = (key: keyof ListMore): LeadFilters => ({
    ...filters,
    more: { ...more, [key]: null, ...(key === "sort" ? { order: null } : {}) },
  });
  const chips: { key: string; label: string; clear: LeadFilters }[] = [];
  if (filters.q.trim())
    chips.push({
      key: "q",
      label: `“${filters.q.trim()}”`,
      clear: { ...filters, q: "" },
    });
  if (filters.who !== defaultWho)
    chips.push({
      key: "who",
      label: WHO.find((item) => item.key === filters.who)?.label ?? "",
      clear: { ...filters, who: defaultWho },
    });
  if (filters.pipeline)
    chips.push({
      key: "pipeline",
      label:
        pipes.find((item) => item.key === filters.pipeline)?.name ??
        "One pipeline",
      clear: { ...filters, pipeline: null },
    });
  if (more.due)
    chips.push({
      key: "due",
      label: DUE_WORDS[more.due],
      clear: without("due"),
    });
  // In Follow-ups the split is its own row of tabs, not a chip.
  if (more.when && more.view !== "follow_ups")
    chips.push({
      key: "when",
      label: `Follow-up ${WHEN_WORDS[more.when].toLowerCase()}`,
      clear: without("when"),
    });
  if (more.contact)
    chips.push({
      key: "contact",
      label: SINCE_WORDS[more.contact],
      clear: without("contact"),
    });
  if (more.created)
    chips.push({
      key: "created",
      label: MADE_WORDS[more.created],
      clear: without("created"),
    });
  if (more.source)
    chips.push({
      key: "source",
      label: SOURCE_WORDS[more.source] ?? more.source,
      clear: without("source"),
    });
  if (more.sort)
    chips.push({
      key: "sort",
      label: sortLabel(more),
      clear: without("sort"),
    });
  return chips;
}

/** The filters that narrow the list, in their chips' words: an empty list says which
 *  hid the leads (robot J181, 2 Nov 2026). A sort hides nothing. */
export function filterNames(
  filters: LeadFilters,
  defaultWho: Scope,
  pipes: Pipe[] = [],
): string[] {
  return filterChips(filters, defaultWho, pipes)
    .filter((chip) => chip.key !== "sort")
    .map((chip) => chip.label);
}

/** The filters that are on, each with its own ×. */
export function ActiveFilters({
  filters,
  defaultWho,
  pipes,
  onChange,
}: {
  filters: LeadFilters;
  defaultWho: Scope;
  pipes: Pipe[];
  onChange: (next: LeadFilters) => void;
}) {
  const chips = filterChips(filters, defaultWho, pipes);
  if (!chips.length) return null;
  return (
    <ul className={styles.activeFilters} aria-label="Filters on">
      {chips.map((chip) => (
        <li key={chip.key}>
          <button
            type="button"
            className={styles.activeFilter}
            aria-label={`Remove filter ${chip.label}`}
            onClick={() => onChange(chip.clear)}
          >
            <span>{chip.label}</span>
            <X size={14} aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  );
}

/** One summary per question; opening it reveals one answer per 48 px row.
 * Native exclusive details keep choices in this sheet, with no stacked overlay. */
function Choices<T extends string>({
  label,
  words,
  value,
  onChange,
  any = "Any",
}: {
  label: string;
  words: Record<T, string>;
  value: T | null | undefined;
  onChange: (next: T | null) => void;
  any?: string;
}) {
  // The one picker, opening in place inside the sheet (owner, 31 Oct 2026).
  return (
    <Picker
      mode="inline"
      title={label}
      label={label}
      value={value ?? null}
      all={{ label: any }}
      options={Object.entries<string>(words).map(([key, word]) => ({
        key,
        label: word,
      }))}
      onChange={(next) => onChange(next as T | null)}
    />
  );
}

export function FilterSheet({
  open,
  onClose,
  filters,
  defaultWho,
  canPickWho,
  pipes,
  onApply,
  sellerPicker,
  onClearAll,
  fileSources = [],
}: {
  open: boolean;
  onClose: () => void;
  filters: LeadFilters;
  /** The organisation's own lists, from files' Source columns (ph1-18). */
  fileSources?: readonly string[];
  defaultWho: Scope;
  /** Owners and admins pick whose leads; a seller's are always their own. */
  canPickWho: boolean;
  /** Several pipelines: one, or all of them. */
  pipes: Pipe[];
  onApply: (next: LeadFilters) => void;
  sellerPicker?: ReactNode;
  onClearAll?: () => void;
}) {
  // A fresh sheet each opening starts from the filters on now.
  const [draft, setDraft] = useState(filters);
  const more = draft.more ?? {};
  const setMore = (next: ListMore) =>
    setDraft({ ...draft, more: { ...more, ...next } });
  const apply = (next: LeadFilters) => {
    onApply({ ...next, q: next.q.trim() });
    onClose();
  };
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Filter Leads"
      wide="center"
      footer={
        <div className={styles.filterActions}>
          <Button
            variant="ghost"
            onClick={() => {
              if (onClearAll) {
                onClearAll();
                onClose();
              } else
                apply({ who: defaultWho, pipeline: null, q: "", more: {} });
            }}
          >
            Clear Filters
          </Button>
          <Button variant="primary" onClick={() => apply(draft)}>
            Show Results
          </Button>
        </div>
      }
    >
      <form
        className={styles.filterForm}
        onSubmit={(event) => {
          event.preventDefault();
          apply(draft);
        }}
      >
        {/* Pipeline first: for a team with several, the choice that matters most
            (orchestrator, 25 Oct 2026); then whose leads. */}
        {pipes.length > 1 ? (
          <Choices
            label="Pipeline"
            words={Object.fromEntries(
              pipes.map((pipe) => [pipe.key, pipe.name]),
            )}
            value={draft.pipeline}
            any="All pipelines"
            onChange={(pipeline) => setDraft({ ...draft, pipeline })}
          />
        ) : null}
        {canPickWho ? (
          <Choices
            label="Whose leads"
            words={{ mine: "Mine", unassigned: "No owner" }}
            value={draft.who === "team" ? null : draft.who}
            any="Everyone"
            onChange={(who) =>
              setDraft({ ...draft, who: (who as Scope | null) ?? "team" })
            }
          />
        ) : null}
        {sellerPicker ? (
          <details className={styles.pickerGroup} name="lead-filter-choice">
            <summary>
              <span>One seller</span>
              <ChevronDown size={16} aria-hidden="true" />
            </summary>
            <div className={styles.sellerChoices}>{sellerPicker}</div>
          </details>
        ) : null}
        {/* Dipak's handoff (31 Oct 2026, items 50-52): source, date and
            follow-up; search is on the page. */}
        <Choices
          label="Lead source"
          words={{
            ...SOURCE_WORDS,
            ...Object.fromEntries(fileSources.map((name) => [name, name])),
          }}
          value={more.source}
          any="Every source"
          onChange={(source) => setMore({ source })}
        />
        <Choices
          label="Date"
          words={MADE_WORDS}
          value={more.created}
          onChange={(created) => setMore({ created })}
        />
        <Choices
          label="Follow-up"
          words={WHEN_WORDS}
          value={more.when}
          onChange={(when) => setMore({ when, due: null })}
        />
        <Choices
          label="Sort by"
          words={SORT_CHOICES}
          value={
            more.sort === "created" && more.order === "asc" ? OLDEST : more.sort
          }
          onChange={(sort) =>
            setMore(
              sort === OLDEST
                ? { sort: "created", order: "asc" }
                : { sort, order: null },
            )
          }
        />
      </form>
    </Sheet>
  );
}
