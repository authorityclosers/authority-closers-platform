"use client";

/**
 * Each seller, one row (competitor teardown #18, 1 Nov 2026): what they tried,
 * connected and talked, the follow-ups they did, what their wins were worth,
 * their longest break and the calls without a recording. Tap a column's head
 * (on a phone, pick from Sort) to sort by it, a seller for their day; Export
 * takes the rows as sorted. For owners and managers only: a seller never sees
 * the others (the owner's rule, no rankings for sellers).
 */

import { ChevronDown, ChevronUp, Download } from "lucide-react";
import { useState } from "react";

import { breakLength } from "../dashboard/home-today";
import { inr } from "../dashboard/revenue-client";
import { Picker } from "../ui/picker";
import type { SellerEffort } from "./performance-client";
import styles from "./performance.module.css";

export type Figure =
  | "tried"
  | "connected"
  | "talk"
  | "follow_ups"
  | "won"
  | "gap"
  | "unrecorded";
export type Column = "name" | Figure;

export const FIGURES: { key: Figure; label: string; title: string }[] = [
  { key: "tried", label: "Tried", title: "Calls tried" },
  { key: "connected", label: "Connected", title: "Calls that connected" },
  { key: "talk", label: "Talk time", title: "Time on connected calls" },
  { key: "follow_ups", label: "F/U done", title: "Calls to leads past New" },
  { key: "won", label: "Wins ₹", title: "What their Won leads were worth" },
  {
    key: "gap",
    label: "Longest break",
    title: "The longest gap between calls in work hours",
  },
  {
    key: "unrecorded",
    label: "No recording",
    title: "Connected calls without a recording, today",
  },
];

/** A seller's figure for a column, as a number to sort by. */
export function figure(seller: SellerEffort, key: Figure): number {
  switch (key) {
    case "tried":
      return seller.inbound.attempted + seller.cold.attempted;
    case "connected":
      return seller.inbound.connected + seller.cold.connected;
    case "talk":
      return seller.inbound.talk_seconds + seller.cold.talk_seconds;
    case "follow_ups":
      return seller.follow_ups_done ?? 0;
    case "won":
      return seller.won_amount ?? 0;
    case "gap":
      return seller.breaks[0]?.minutes ?? 0;
    case "unrecorded":
      return seller.missing_recordings;
  }
}

/** How a figure reads in its cell. */
export function shown(seller: SellerEffort, key: Figure): string {
  const value = figure(seller, key);
  if (key === "talk") return breakLength(Math.round(value / 60));
  if (key === "won") return value ? inr(value) : "–";
  if (key === "gap") return value ? breakLength(value) : "–";
  return String(value);
}

/** Red: an unexplained hour-long break, or calls without a recording. */
const red = (seller: SellerEffort, key: Figure) =>
  (key === "unrecorded" && seller.missing_recordings > 0) ||
  (key === "gap" &&
    !!seller.breaks[0] &&
    !seller.breaks[0].planned &&
    seller.breaks[0].minutes >= 60);

const byName = (a: SellerEffort, b: SellerEffort) =>
  a.name.localeCompare(b.name);

/** The rows in the order picked: by name, A to Z, unless a column is. */
export function sortSellers(
  sellers: readonly SellerEffort[],
  key: Column,
  down: boolean,
): SellerEffort[] {
  return [...sellers].sort((a, b) => {
    if (key === "name") return down ? byName(b, a) : byName(a, b);
    const diff = figure(a, key) - figure(b, key);
    return (down ? -diff : diff) || byName(a, b);
  });
}

const csvCell = (text: string) =>
  /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;

/** The rows as a spreadsheet, plain numbers (Export). */
export function exportCsv(sellers: readonly SellerEffort[]): string {
  const head = [
    "Seller",
    "Tried",
    "Connected",
    "Talk time (min)",
    "Follow-ups done",
    "Wins (₹)",
    "Longest break (min)",
    "Calls without a recording today",
  ];
  const lines = sellers.map((seller) =>
    [
      seller.name,
      figure(seller, "tried"),
      figure(seller, "connected"),
      Math.round(figure(seller, "talk") / 60),
      figure(seller, "follow_ups"),
      figure(seller, "won"),
      figure(seller, "gap"),
      figure(seller, "unrecorded"),
    ]
      .map((value) => csvCell(String(value)))
      .join(","),
  );
  return [head.map(csvCell).join(","), ...lines].join("\n");
}

function save(text: string, file: string) {
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/csv;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = file;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function Arrow({ on, down }: { on: boolean; down: boolean }) {
  if (!on) return null;
  return down ? (
    <ChevronDown size={14} aria-hidden="true" />
  ) : (
    <ChevronUp size={14} aria-hidden="true" />
  );
}

export function SellerTable({
  sellers,
  file,
  onOpen,
}: {
  sellers: readonly SellerEffort[];
  /** The export's file name: "performance-today.csv". */
  file: string;
  onOpen: (seller: SellerEffort) => void;
}) {
  const [sort, setSort] = useState<{ key: Column; down: boolean }>({
    key: "name",
    down: false,
  });
  const rows = sortSellers(sellers, sort.key, sort.down);
  const by = (key: Column) =>
    setSort((current) =>
      current.key === key
        ? { key, down: !current.down }
        : { key, down: key !== "name" },
    );
  const order = (key: Column) =>
    sort.key === key ? (sort.down ? "descending" : "ascending") : "none";
  return (
    <section className={styles.card} aria-labelledby="sellers-title">
      <div className={styles.tableHead}>
        <h2 id="sellers-title">Each seller</h2>
        <button
          type="button"
          className={styles.export}
          onClick={() => save(exportCsv(rows), file)}
        >
          <Download size={16} aria-hidden="true" />
          Export
        </button>
      </div>
      <div className={styles.sortPicker}>
        <Picker
          title="Sort sellers by"
          label="Sort:"
          value={sort.key}
          options={[
            { key: "name", label: "Name" },
            ...FIGURES.map(({ key, label }) => ({ key, label })),
          ]}
          onChange={(key) => {
            if (key) setSort({ key: key as Column, down: key !== "name" });
          }}
        />
      </div>
      <table className={styles.sellerTable} aria-label="Each seller">
        <thead>
          <tr>
            <th scope="col" aria-sort={order("name")}>
              <button type="button" onClick={() => by("name")}>
                Seller
                <Arrow on={sort.key === "name"} down={sort.down} />
              </button>
            </th>
            {FIGURES.map((item) => (
              <th key={item.key} scope="col" aria-sort={order(item.key)}>
                <button
                  type="button"
                  title={item.title}
                  onClick={() => by(item.key)}
                >
                  {item.label}
                  <Arrow on={sort.key === item.key} down={sort.down} />
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((seller) => (
            <tr key={seller.person_id} data-seller={seller.person_id}>
              <th scope="row">
                <button
                  type="button"
                  className={styles.sellerName}
                  onClick={() => onOpen(seller)}
                >
                  {seller.name}
                </button>
              </th>
              {FIGURES.map((item) => (
                <td
                  key={item.key}
                  data-red={red(seller, item.key) || undefined}
                >
                  {shown(seller, item.key)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <ul className={styles.sellerCards} aria-label="Each seller">
        {rows.map((seller) => (
          <li key={seller.person_id}>
            <button
              type="button"
              className={styles.sellerCard}
              onClick={() => onOpen(seller)}
            >
              <strong>{seller.name}</strong>
              <dl>
                {FIGURES.map((item) => (
                  <div key={item.key}>
                    <dt>{item.label}</dt>
                    <dd data-red={red(seller, item.key) || undefined}>
                      {shown(seller, item.key)}
                    </dd>
                  </div>
                ))}
              </dl>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
