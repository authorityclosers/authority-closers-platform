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

import { Check, ChevronDown, SlidersHorizontal, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button, Field } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import type {
  ListDue,
  ListMade,
  ListMore,
  ListSince,
  ListSort,
} from "./leads-client";
import type { Scope } from "./list-view";
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
  created: "Newest",
};
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
    more.sort
      ? `By ${SORT_WORDS[more.sort].toLowerCase()}${more.order === "desc" ? ", reversed" : ""}`
      : null,
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
      Filter
      {count ? (
        <span className={styles.filterCount} aria-hidden="true">
          {count}
        </span>
      ) : null}
    </button>
  );
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
      label: `By ${SORT_WORDS[more.sort].toLowerCase()}${more.order === "desc" ? ", reversed" : ""}`,
      clear: without("sort"),
    });
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
  return (
    <details className={styles.pickerGroup} name="lead-filter-choice">
      <summary>
        <span>{label}</span>
        <span className={styles.pickerValue}>{value ? words[value] : any}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </summary>
      <div className={styles.pickerOptions} role="group" aria-label={label}>
        {[["", any], ...Object.entries(words)].map(([key, word]) => (
          <button
            key={key}
            type="button"
            className={styles.pickerRow}
            aria-pressed={(value ?? "") === key}
            onClick={(event) => {
              onChange(key ? (key as T) : null);
              const group = event.currentTarget.closest("details");
              if (group) {
                group.open = false;
                group.querySelector("summary")?.focus();
              }
            }}
          >
            <span>{String(word)}</span>
            {(value ?? "") === key ? (
              <Check size={18} aria-hidden="true" />
            ) : null}
          </button>
        ))}
      </div>
    </details>
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
}: {
  open: boolean;
  onClose: () => void;
  filters: LeadFilters;
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
      title="Filter and sort"
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
            Clear all
          </Button>
          <Button variant="primary" onClick={() => apply(draft)}>
            Show leads
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
        <Field label="Name or number">
          <input
            type="search"
            value={draft.q}
            placeholder="Name, company, city or phone"
            maxLength={80}
            enterKeyHint="search"
            onChange={(event) => setDraft({ ...draft, q: event.target.value })}
          />
        </Field>
        <Choices
          label="Sort by"
          words={SORT_WORDS}
          value={more.sort}
          onChange={(sort) => setMore({ sort, order: null })}
        />
        <Choices
          label="Next follow-up"
          words={DUE_WORDS}
          value={more.due}
          onChange={(due) => setMore({ due })}
        />
        <Choices
          label="Last contact"
          words={SINCE_WORDS}
          value={more.contact}
          onChange={(contact) => setMore({ contact })}
        />
        <Choices
          label="Came in"
          words={MADE_WORDS}
          value={more.created}
          onChange={(created) => setMore({ created })}
        />
        <Choices
          label="Source"
          words={SOURCE_WORDS}
          value={more.source}
          any="Every source"
          onChange={(source) => setMore({ source })}
        />
      </form>
    </Sheet>
  );
}
