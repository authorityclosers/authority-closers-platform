"use client";

/**
 * When the leads came in (owner, 16 Nov 2026): a date chip beside the stage
 * pick on Leads (Today, Yesterday, 7 days, 30 days, or a range of days from a
 * calendar), answered by the server by each lead's arrival; and, for owners and
 * managers, Leads per day, a small bar chart of the leads received each day.
 */

import { useEffect, useState } from "react";

import { Button, Field } from "../ui/kit";
import { Picker } from "../ui/picker";
import { Sheet } from "../ui/sheet";
import {
  readLeadsPerDay,
  type LeadSide,
  type LeadsPerDay,
  type ListMade,
  type ListMore,
} from "./leads-client";
import styles from "./leads.module.css";

const CUSTOM = "custom";
const PER_DAY = "per-day";

/** The chip's choices, in the order of the day. */
export const ARRIVED_WORDS: Record<Exclude<ListMade, "history">, string> = {
  today: "Today",
  yesterday: "Yesterday",
  week: "7 days",
  month: "30 days",
};

/** "2026-11-16" as the business reads it: "16 Nov". */
export function dayWords(day: string): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}

/** A date input's value for a day `back` days before today, on this phone. */
export function dayInput(back = 0, now: Date = new Date()): string {
  const at = new Date(now);
  at.setDate(at.getDate() - back);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

/** The range's words: "2 Nov – 9 Nov", or one day. */
export function rangeWords(since?: string | null, until?: string | null) {
  if (since && until)
    return since === until
      ? dayWords(since)
      : `${dayWords(since)} – ${dayWords(until)}`;
  if (since) return `From ${dayWords(since)}`;
  if (until) return `To ${dayWords(until)}`;
  return null;
}

/** The days a list's date choice covers, for Leads per day (30 by default). */
export function rangeOf(more: ListMore, now: Date = new Date()) {
  if (more.since || more.until)
    return {
      since: more.since ?? more.until!,
      until: more.until ?? dayInput(0, now),
    };
  const back =
    more.created === "today"
      ? 0
      : more.created === "yesterday"
        ? 1
        : more.created === "week"
          ? 6
          : 29;
  return {
    since: dayInput(back, now),
    until: dayInput(more.created === "yesterday" ? 1 : 0, now),
  };
}

export function ArrivedPick({
  more,
  onChange,
  onPerDay,
}: {
  more: ListMore;
  onChange: (next: Partial<ListMore>) => void;
  /** Owners and managers: Leads per day, from the date chip, since the stage
   *  views Leads opens on have no settings gear. */
  onPerDay?: () => void;
}) {
  const [custom, setCustom] = useState(false);
  // Each opening starts from the range on now.
  const [round, setRound] = useState(0);
  const range = rangeWords(more.since, more.until);
  const value = range
    ? CUSTOM
    : more.created && more.created !== "history"
      ? more.created
      : null;
  return (
    <>
      <Picker
        variant="chip"
        title="Came in"
        ariaLabel={`Came in: ${range ?? (value ? ARRIVED_WORDS[value as keyof typeof ARRIVED_WORDS] : "any day")}`}
        value={value}
        options={[
          ...Object.entries(ARRIVED_WORDS).map(([key, label]) => ({
            key,
            label,
          })),
          { key: CUSTOM, label: range ?? "Custom dates…" },
          ...(onPerDay ? [{ key: PER_DAY, label: "Leads per day" }] : []),
        ]}
        all={{ label: "Any day" }}
        display={
          <span>
            {range ??
              (value
                ? ARRIVED_WORDS[value as keyof typeof ARRIVED_WORDS]
                : "Any day")}
          </span>
        }
        onChange={(key) => {
          if (key === PER_DAY) onPerDay?.();
          else if (key === CUSTOM) {
            setRound((count) => count + 1);
            setCustom(true);
          } else
            onChange({
              created: key as ListMade | null,
              since: null,
              until: null,
            });
        }}
      />
      <CustomDates
        key={round}
        open={custom}
        since={more.since ?? null}
        until={more.until ?? null}
        onClose={() => setCustom(false)}
        onApply={(since, until) => {
          setCustom(false);
          onChange({ created: null, since, until });
        }}
      />
    </>
  );
}

function CustomDates({
  open,
  since,
  until,
  onClose,
  onApply,
}: {
  open: boolean;
  since: string | null;
  until: string | null;
  onClose: () => void;
  onApply: (since: string, until: string) => void;
}) {
  const [from, setFrom] = useState(since ?? dayInput(6));
  const [to, setTo] = useState(until ?? dayInput(0));
  const valid = !!from && !!to && from <= to;
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Came in between"
      wide="center"
      footer={
        <div className={styles.filterActions}>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!valid}
            onClick={() => valid && onApply(from, to)}
          >
            Show leads
          </Button>
        </div>
      }
    >
      <div className={styles.arrivedDates}>
        <Field label="From">
          <input
            type="date"
            value={from}
            max={to || dayInput(0)}
            onChange={(event) => setFrom(event.target.value)}
          />
        </Field>
        <Field label="To">
          <input
            type="date"
            value={to}
            min={from}
            max={dayInput(0)}
            onChange={(event) => setTo(event.target.value)}
          />
        </Field>
      </div>
    </Sheet>
  );
}

/** Leads per day, for owners and managers: the list's dates (30 days by
 *  default), one bar a day, the day's count on hover and in a table. */
export function LeadsPerDaySheet({
  open,
  onClose,
  more,
  side,
}: {
  open: boolean;
  onClose: () => void;
  more: ListMore;
  side: LeadSide | null;
}) {
  const { since, until } = rangeOf(more);
  const [data, setData] = useState<{ key: string; value: LeadsPerDay } | null>(
    null,
  );
  // The range whose read failed, if any.
  const [failed, setFailed] = useState<string | null>(null);
  const key = `${since}|${until}|${side ?? ""}`;
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    readLeadsPerDay(since, until, side, abort.signal).then(
      (value) => setData({ key, value }),
      () => {
        if (!abort.signal.aborted) setFailed(key);
      },
    );
    return () => abort.abort();
  }, [open, key, since, until, side]);
  const shown = data?.key === key ? data.value : null;
  const top = shown ? Math.max(1, ...shown.days.map((day) => day.count)) : 1;
  return (
    <Sheet open={open} onClose={onClose} title="Leads per day" wide="center">
      <div className={styles.perDay} data-leads-per-day="">
        <p className={styles.perDayHead}>
          <strong>{shown ? shown.total.toLocaleString("en-IN") : "…"}</strong>{" "}
          {shown?.total === 1 ? "lead" : "leads"} came in ·{" "}
          {rangeWords(since, until)}
        </p>
        {failed === key && !shown ? (
          <p className={styles.hint} role="alert">
            Couldn&apos;t read the days. Try again in a moment.
          </p>
        ) : shown ? (
          <>
            <div
              className={styles.perDayBars}
              role="img"
              aria-label={`Leads per day, ${rangeWords(since, until)}`}
            >
              {shown.days.map((day) => (
                <span
                  key={day.day}
                  className={styles.perDayBar}
                  title={`${dayWords(day.day)}: ${day.count}`}
                  data-empty={day.count ? undefined : ""}
                  style={{ height: `${(day.count / top) * 100}%` }}
                />
              ))}
            </div>
            <p className={styles.perDayAxis} aria-hidden="true">
              <span>{dayWords(shown.days[0]?.day ?? since)}</span>
              <span>{dayWords(shown.days.at(-1)?.day ?? until)}</span>
            </p>
            <table className={styles.srOnly}>
              <caption>Leads per day</caption>
              <tbody>
                {shown.days.map((day) => (
                  <tr key={day.day}>
                    <th scope="row">{dayWords(day.day)}</th>
                    <td>{day.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <div className={styles.perDayBars} aria-busy="true" />
        )}
      </div>
    </Sheet>
  );
}
