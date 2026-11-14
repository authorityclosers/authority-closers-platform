"use client";

/**
 * Filter reports (Dipak's Reports V4 spec, sections 8-11 and 22): the shared
 * bottom sheet with Lead type and a From–To calendar. Choices are a draft
 * until "Show N reports" applies them; closing (×, a tap outside, Back) keeps
 * what was applied before. The button counts the reports the draft would show
 * and refuses a range with only one date ("Select an end date").
 */

import { CalendarDays } from "lucide-react";
import { useId, useState } from "react";

import { Picker } from "../ui/picker";
import { Sheet } from "../ui/sheet";
import {
  ALL_LEAD_TYPES,
  LEAD_TYPE_OPTIONS,
  completeRange,
  dayWords,
  isLeadTypeFilter,
  matchesLeadType,
  pickDay,
  showButtonLabel,
  visibleReports,
  type LeadTypeFilter,
  type ReportQuery,
  type ReportRow,
} from "./report-filter";
import { RangeCalendar, monthOf, type CalendarMonth } from "./range-calendar";
import styles from "./report-library.module.css";

type Draft = {
  leadType: LeadTypeFilter | null;
  from: string | null;
  to: string | null;
  picking: "from" | "to";
};

export function FilterSheet({
  open,
  applied,
  rows,
  today,
  onApply,
  onClose,
}: {
  open: boolean;
  /** What is applied now: the draft starts from it each time the sheet opens. */
  applied: ReportQuery;
  rows: readonly ReportRow[];
  today: string;
  onApply: (filters: Pick<ReportQuery, "leadType" | "from" | "to">) => void;
  onClose: () => void;
}) {
  // Each opening starts a fresh draft from what is applied; the body stays
  // while the sheet slides away.
  const [round, setRound] = useState(0);
  const [wasOpen, setWasOpen] = useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setRound((value) => value + 1);
  }
  return (
    <Sheet open={open} onClose={onClose} title="Filter reports" wide="center">
      {round > 0 ? (
        <FilterBody
          key={round}
          open={open}
          applied={applied}
          rows={rows}
          today={today}
          onApply={onApply}
        />
      ) : null}
    </Sheet>
  );
}

function FilterBody({
  open,
  applied,
  rows,
  today,
  onApply,
}: {
  open: boolean;
  applied: ReportQuery;
  rows: readonly ReportRow[];
  today: string;
  onApply: (filters: Pick<ReportQuery, "leadType" | "from" | "to">) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => ({
    leadType: applied.leadType,
    from: applied.from,
    to: applied.to,
    picking: applied.from && !applied.to ? "to" : "from",
  }));
  // The current month first; a range already chosen opens on its month.
  const [month, setMonth] = useState<CalendarMonth>(() =>
    monthOf(applied.to ?? applied.from ?? today),
  );
  const [refused, setRefused] = useState(false);
  const labelId = useId();
  const rangeId = useId();
  const partial = Boolean(draft.from) !== Boolean(draft.to);
  const range = completeRange(draft.from, draft.to);
  const shown = visibleReports(rows, {
    query: applied.query,
    leadType: draft.leadType,
    from: range?.from ?? null,
    to: range?.to ?? null,
  }).length;
  const total = visibleReports(rows, {
    ...applied,
    leadType: null,
    from: null,
    to: null,
  }).length;
  const counts = new Map(
    LEAD_TYPE_OPTIONS.map((option) => [
      option.key,
      rows.filter((row) => matchesLeadType(row, option.key)).length,
    ]),
  );

  const apply = () => {
    if (partial) {
      setRefused(true);
      return;
    }
    onApply({
      leadType: draft.leadType,
      from: range?.from ?? null,
      to: range?.to ?? null,
    });
  };

  return (
    <div
      className={styles.sheetBody}
      data-filter-sheet={open ? "open" : "closed"}
    >
      <div className={styles.sheetScroll}>
        <div className={styles.field}>
          <span className={styles.fieldLabel} id={labelId}>
            Lead type
          </span>
          <Picker
            title="Lead type"
            mode="inline"
            ariaLabel="Lead type"
            describedBy={labelId}
            value={draft.leadType}
            all={{ label: ALL_LEAD_TYPES, count: rows.length }}
            options={LEAD_TYPE_OPTIONS.map((option) => ({
              key: option.key,
              label: option.label,
              count: counts.get(option.key) ?? 0,
            }))}
            onChange={(key) =>
              setDraft((current) => ({
                ...current,
                leadType: isLeadTypeFilter(key) ? key : null,
              }))
            }
            className={styles.picker}
          />
        </div>

        <div className={styles.dateHead}>
          <span className={styles.fieldLabel} id={rangeId}>
            Report date range
          </span>
          <CalendarDays size={18} aria-hidden="true" />
        </div>
        <div
          className={styles.rangeSlots}
          role="group"
          aria-labelledby={rangeId}
        >
          {(["from", "to"] as const).map((slot) => {
            const value = draft[slot];
            return (
              <button
                key={slot}
                type="button"
                className={styles.slot}
                data-slot={slot}
                aria-pressed={draft.picking === slot}
                onClick={() =>
                  setDraft((current) => ({ ...current, picking: slot }))
                }
              >
                <span className={styles.slotName}>
                  {slot === "from" ? "From" : "To"}
                </span>
                <span
                  className={styles.slotValue}
                  data-empty={value ? undefined : ""}
                >
                  {value
                    ? dayWords(value)
                    : slot === "from"
                      ? "Select start date"
                      : "Select end date"}
                </span>
              </button>
            );
          })}
        </div>
        <RangeCalendar
          month={month}
          from={draft.from}
          to={draft.to}
          today={today}
          onMonth={setMonth}
          onPick={(day) => {
            setRefused(false);
            setDraft((current) => ({ ...current, ...pickDay(current, day) }));
          }}
        />
        <div className={styles.calendarFoot}>
          <p className={styles.hint} aria-live="polite" data-date-hint="">
            {refused
              ? "Select an end date"
              : !draft.from
                ? "Tap a start date, then an end date."
                : !draft.to
                  ? "Now select an end date."
                  : "Date range selected."}
          </p>
          <button
            type="button"
            className={styles.quiet}
            onClick={() => {
              setRefused(false);
              setDraft((current) => ({
                ...current,
                from: null,
                to: null,
                picking: "from",
              }));
              setMonth(monthOf(today));
            }}
          >
            Clear dates
          </button>
        </div>
        <p className={styles.helper}>
          With no filters selected, all reports are shown, newest first.
        </p>
      </div>
      <div className={styles.sheetActions}>
        <button
          type="button"
          className={styles.secondary}
          onClick={() => {
            setRefused(false);
            setDraft({ leadType: null, from: null, to: null, picking: "from" });
            setMonth(monthOf(today));
          }}
        >
          Reset all
        </button>
        <button
          type="button"
          className={styles.primary}
          data-apply=""
          aria-disabled={partial}
          onClick={apply}
        >
          {partial ? "Select an end date" : showButtonLabel(shown, total)}
        </button>
      </div>
    </div>
  );
}
