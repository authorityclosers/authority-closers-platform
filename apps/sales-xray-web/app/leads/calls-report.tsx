"use client";

/**
 * Calls by seller by day (build list row 18; Salestrail's manager dashboard,
 * NeoDove's user report): for a date range, each seller's calls, connected
 * calls, talk time and missed calls, counted the way My day counts them. Up to
 * two weeks show a column per day; any range up to 92 days downloads as a CSV
 * with one row per seller per day.
 */

import { Download } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, Field, Panel, Skeleton } from "../ui/kit";
import {
  LeadsError,
  minutesLabel,
  readCallReport,
  type CallReport,
} from "./leads-client";
import styles from "./leads.module.css";

const DAY_COLUMNS = 14;

/** YYYY-MM-DD in the viewer's own calendar. */
export function dayValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function dayLabel(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
  });
}

const cell = (value: string) =>
  /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;

/** One row per seller per day, for a spreadsheet. */
export function callsCsv(report: CallReport): string {
  const lines = ["Seller,Date,Calls,Connected,Talk minutes,Missed calls"];
  for (const seller of report.sellers)
    for (const day of seller.days)
      lines.push(
        [
          cell(seller.name),
          day.day,
          day.calls,
          day.connected,
          Math.round(day.talk_seconds / 60),
          day.missed,
        ].join(","),
      );
  return `${lines.join("\n")}\n`;
}

function download(report: CallReport) {
  const blob = new Blob([callsCsv(report)], { type: "text/csv" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `calls-by-seller-${report.start}-to-${report.end}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function CallsReport() {
  const [end, setEnd] = useState(() => dayValue(new Date()));
  const [start, setStart] = useState(() => {
    const week = new Date();
    week.setDate(week.getDate() - 6);
    return dayValue(week);
  });
  const [report, setReport] = useState<CallReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    readCallReport(start, end, controller.signal)
      .then((next) => {
        setReport(next);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          reason instanceof LeadsError
            ? reason.message
            : "The calls didn't load.",
        );
      });
    return () => controller.abort();
  }, [start, end]);

  const days = report?.sellers[0]?.days.map((day) => day.day) ?? [];
  const perDay = days.length <= DAY_COLUMNS;

  return (
    <Panel
      title="Calls by seller"
      sub="by day"
      tools={
        <Button
          variant="ghost"
          disabled={!report}
          onClick={() => report && download(report)}
        >
          <Download size={14} aria-hidden="true" />
          CSV
        </Button>
      }
    >
      <div className={styles.form}>
        <div className={styles.row}>
          <Field label="From">
            <input
              type="date"
              value={start}
              max={end}
              onChange={(event) => setStart(event.target.value)}
            />
          </Field>
          <Field label="To">
            <input
              type="date"
              value={end}
              min={start}
              onChange={(event) => setEnd(event.target.value)}
            />
          </Field>
        </div>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : !report ? (
          <Skeleton height={140} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table} aria-label="Calls by seller">
              <thead>
                <tr>
                  <th>Seller</th>
                  {perDay
                    ? days.map((day) => (
                        <th key={day} data-num>
                          {dayLabel(day)}
                        </th>
                      ))
                    : null}
                  <th data-num>Calls</th>
                  <th data-num>Connected</th>
                  <th data-num>Talk</th>
                  <th data-num>Missed</th>
                </tr>
              </thead>
              <tbody>
                {report.sellers.map((seller) => (
                  <tr key={seller.person_id}>
                    <th scope="row">{seller.name}</th>
                    {perDay
                      ? seller.days.map((day) => (
                          <td
                            key={day.day}
                            data-num
                            title={`${day.connected} connected`}
                          >
                            {day.calls || "–"}
                          </td>
                        ))
                      : null}
                    <td data-num>{seller.calls}</td>
                    <td data-num>{seller.connected}</td>
                    <td data-num>
                      {seller.talk_seconds
                        ? minutesLabel(seller.talk_seconds)
                        : "–"}
                    </td>
                    <td data-num>{seller.missed || "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {report && !perDay ? (
          <p className={styles.hint}>
            Over two weeks, the CSV has each day; the table shows the totals.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
