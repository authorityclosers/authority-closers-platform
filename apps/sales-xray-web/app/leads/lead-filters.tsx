"use client";

/**
 * Leads → Filter (Leads header, agreed with Liquid Glass, 22 Oct 2026): one chip
 * on the header row says how many filters are on; its sheet holds the name or
 * number, whose leads and the pipeline, applied together. Filters that are on
 * show as removable chips under the row. The header's own search (every screen)
 * finds anything; this only narrows the list.
 */

import { SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";

import { Button, Field, Segmented } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import type { Scope } from "./list-view";
import styles from "./leads.module.css";

export type LeadFilters = {
  who: Scope;
  pipeline: string | null;
  q: string;
};

type Pipe = { key: string; name: string };

const WHO: { key: Scope; label: string }[] = [
  { key: "team", label: "Everyone" },
  { key: "mine", label: "Mine" },
  { key: "unassigned", label: "No owner" },
];

/** How many filters narrow the list (whose leads counts when it isn't the default). */
export function filtersOn(filters: LeadFilters, defaultWho: Scope): number {
  return (
    (filters.q.trim() ? 1 : 0) +
    (filters.who !== defaultWho ? 1 : 0) +
    (filters.pipeline ? 1 : 0)
  );
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

export function FilterSheet({
  open,
  onClose,
  filters,
  defaultWho,
  canPickWho,
  pipes,
  onApply,
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
}) {
  // A fresh sheet each opening starts from the filters on now.
  const [draft, setDraft] = useState(filters);
  const apply = (next: LeadFilters) => {
    onApply({ ...next, q: next.q.trim() });
    onClose();
  };
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Filter leads"
      wide="center"
      footer={
        <div className={styles.filterActions}>
          <Button
            variant="ghost"
            onClick={() => apply({ who: defaultWho, pipeline: null, q: "" })}
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
        <Field label="Name or number">
          <input
            type="search"
            value={draft.q}
            placeholder="Name, company, city or phone"
            maxLength={80}
            enterKeyHint="search"
            autoFocus
            onChange={(event) => setDraft({ ...draft, q: event.target.value })}
          />
        </Field>
        {canPickWho ? (
          <div className={styles.filterGroup}>
            <span className={styles.stepLabel}>Whose leads</span>
            <Segmented
              label="Whose leads"
              items={WHO}
              value={draft.who}
              onChange={(who) => setDraft({ ...draft, who })}
            />
          </div>
        ) : null}
        {pipes.length === 2 ? (
          <div className={styles.filterGroup}>
            <span className={styles.stepLabel}>Pipeline</span>
            <Segmented
              label="Pipeline"
              items={[
                { key: "", label: "All" },
                ...pipes.map((item) => ({ key: item.key, label: item.name })),
              ]}
              value={draft.pipeline ?? ""}
              onChange={(key) => setDraft({ ...draft, pipeline: key || null })}
            />
          </div>
        ) : pipes.length > 2 ? (
          // Up to eight pipelines: a list, not a row of buttons, on a phone.
          <Field label="Pipeline">
            <select
              value={draft.pipeline ?? ""}
              onChange={(event) =>
                setDraft({ ...draft, pipeline: event.target.value || null })
              }
            >
              <option value="">All pipelines</option>
              {pipes.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
        ) : null}
      </form>
    </Sheet>
  );
}
