"use client";

/**
 * The import's Check (owner's picks, 17 Nov 2026; study 01 §5 S2 part 3):
 * - I3-A on a computer: "Here's what happens to each row", four outcome tiles that add
 *   up to the file's rows (New leads · Already in Sales X-Ray · Repeated in your file ·
 *   Can't be added), tabs over a table of the rows, each with its outcome; a number that
 *   can't be read is underlined with Fix; the rows that can't be added as a file.
 * - From I3-B only the bar: one line split by the four outcomes.
 * - The phone: "9 new leads are ready", the bar, an outcome row each (tap: its rows) and
 *   an amber card per number to fix. Not shorter than the computer's: the same answers.
 *
 * A lead already here is kept as it is unless an owner or admin picks Fill empty details
 * or Replace; Fill never empties a detail. Nothing is written until Import.
 */

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { displayName } from "../display-name";
import { skippedCsv } from "./import-check";
import type {
  Duplicates,
  FileCheck,
  ImportPreview,
  ImportSkip,
} from "./leads-client";
import styles from "./import-rows.module.css";

export type Outcome = "new" | "known" | "repeat" | "bad" | "blank";
type Tab = "all" | "new" | "known" | "repeat" | "cant";

export type RowView = {
  row: number;
  outcome: Outcome;
  name: string;
  phone: string;
  city: string;
  stage: string;
  leadName: string | null;
  sameAs: number | null;
};

/** Each row of the file with its outcome (the check's, else the preview's counts). */
export function rowViews(
  preview: ImportPreview,
  mapping: Record<string, string>,
  check: FileCheck | null,
): RowView[] {
  const fates = check?.rows ?? [];
  const cell = (index: number, field: string) =>
    mapping[field] ? (preview.rows[index]?.[mapping[field]] ?? "").trim() : "";
  return preview.rows.map((_, index) => {
    const fate = fates[index];
    return {
      row: index,
      outcome: fate?.outcome ?? "new",
      name: cell(index, "name"),
      phone: cell(index, "phone"),
      city: cell(index, "city"),
      stage: cell(index, "stage"),
      leadName: fate?.lead_name ?? null,
      sameAs: fate?.same_as ?? null,
    };
  });
}

export function outcomeCounts(rows: readonly RowView[]) {
  const count = (outcome: Outcome) =>
    rows.filter((row) => row.outcome === outcome).length;
  return {
    new: count("new"),
    known: count("known"),
    repeat: count("repeat"),
    cant: count("bad") + count("blank"),
  };
}

const OUTCOME_WORDS: Record<Outcome, string> = {
  new: "New",
  known: "Already here",
  repeat: "Repeated",
  bad: "Can't add",
  blank: "Can't add",
};

const REASON: Record<"bad" | "blank", string> = {
  bad: "Number can't be read",
  blank: "No name, phone or email",
};

/** The rows that can't be added, as a file to fix (the file's columns, then why). */
export function cantAddCsv(
  preview: ImportPreview,
  rows: readonly RowView[],
): string {
  const skipped: ImportSkip[] = rows
    .filter((row) => row.outcome === "bad" || row.outcome === "blank")
    .map((row) => ({
      row: row.row,
      reason: REASON[row.outcome as "bad" | "blank"],
    }));
  return skippedCsv(preview, skipped);
}

const KEPT_WORDS: Record<Duplicates, string> = {
  skip: "kept as it is",
  fill: "empty details filled",
  replace: "details replaced",
};

const CHOICES: { key: Duplicates; label: string; words: string }[] = [
  { key: "skip", label: "Keep as it is", words: "They stay as they are." },
  {
    key: "fill",
    label: "Fill empty details",
    words:
      "Their empty details are filled from the file. Their stage and owner stay.",
  },
  {
    key: "replace",
    label: "Replace details",
    words:
      "Their name and details become the file's where the file has them. Each lead's history keeps what was there.",
  },
];

/** I3-B's bar: one line split by the four outcomes, with its key. */
export function OutcomeBar({ rows }: { rows: readonly RowView[] }) {
  const counts = outcomeCounts(rows);
  const total = rows.length || 1;
  const parts: { key: keyof typeof counts; words: string }[] = [
    { key: "new", words: "new" },
    { key: "known", words: "already here" },
    { key: "repeat", words: "repeated" },
    { key: "cant", words: "can't add" },
  ];
  return (
    <div className={styles.barBox} data-outcome-bar="">
      <div className={styles.bar} aria-hidden="true">
        {parts.map((part) =>
          counts[part.key] ? (
            <i
              key={part.key}
              data-outcome={part.key}
              style={{ flexGrow: counts[part.key] / total }}
            />
          ) : null,
        )}
      </div>
      <ul className={styles.key}>
        {parts.map((part) => (
          <li key={part.key} data-outcome={part.key}>
            <span aria-hidden="true" />
            {counts[part.key]} {part.words}
          </li>
        ))}
      </ul>
    </div>
  );
}

function FixPhone({
  row,
  onFix,
  compact = false,
}: {
  row: RowView;
  onFix: (row: number, phone: string) => void;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(row.phone);
  if (!open)
    return (
      <button
        type="button"
        className={compact ? styles.fixLink : styles.fixButton}
        onClick={() => setOpen(true)}
        aria-label={`Fix the number for row ${row.row + 1}`}
      >
        Fix
      </button>
    );
  return (
    <form
      className={styles.fixForm}
      onSubmit={(event) => {
        event.preventDefault();
        onFix(row.row, value.trim());
        setOpen(false);
      }}
    >
      <input
        aria-label={`Phone number for row ${row.row + 1}`}
        inputMode="tel"
        value={value}
        autoFocus
        onChange={(event) => setValue(event.target.value)}
      />
      <button type="submit" className={styles.fixButton}>
        Save
      </button>
    </form>
  );
}

export function RowsCheck({
  preview,
  mapping,
  check,
  narrow,
  canManage,
  duplicates,
  onDuplicates,
  onFix,
}: {
  preview: ImportPreview;
  mapping: Record<string, string>;
  check: FileCheck | null;
  narrow: boolean;
  canManage: boolean;
  duplicates: Duplicates;
  onDuplicates: (next: Duplicates) => void;
  onFix: (row: number, phone: string) => void;
}) {
  const rows = rowViews(preview, mapping, check);
  const counts = outcomeCounts(rows);
  const [tab, setTab] = useState<Tab>("all");
  const [opened, setOpened] = useState<Outcome | "cant" | null>(null);
  const bad = rows.filter((row) => row.outcome === "bad");
  const base = preview.file_name.replace(/\.[a-z0-9]+$/i, "") || "import";
  const download = counts.cant ? (
    <a
      className={styles.download}
      href={`data:text/csv;charset=utf-8,${encodeURIComponent(cantAddCsv(preview, rows))}`}
      download={`${base}-rows-not-added.csv`}
    >
      Download
    </a>
  ) : null;
  const tiles: {
    key: Tab;
    count: number;
    title: string;
    words: string;
  }[] = [
    { key: "new", count: counts.new, title: "New leads", words: "" },
    {
      key: "known",
      count: counts.known,
      title: "Already in Sales X-Ray",
      words: KEPT_WORDS[duplicates],
    },
    {
      key: "repeat",
      count: counts.repeat,
      title: "Repeated in your file",
      words: "added once",
    },
    {
      key: "cant",
      count: counts.cant,
      title: "Can't be added",
      words: bad.length ? "number can't be read" : "no name, phone or email",
    },
  ];
  const known = counts.known;
  const chosen = CHOICES.find((item) => item.key === duplicates) ?? CHOICES[0];
  const choice =
    known && canManage ? (
      <div className={styles.choice}>
        <span className={styles.choiceLabel}>
          {known === 1
            ? "1 row is already a lead"
            : `${known} rows are already leads`}
        </span>
        <div
          className={styles.chips}
          role="group"
          aria-label="Numbers already leads"
        >
          {CHOICES.map((item) => (
            <button
              key={item.key}
              type="button"
              className={styles.chip}
              aria-pressed={duplicates === item.key}
              onClick={() => onDuplicates(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <p className={styles.muted} data-duplicates={chosen.key}>
          {chosen.words} Never with a blank cell.
        </p>
      </div>
    ) : null;

  if (narrow) {
    const groups: {
      key: Outcome | "cant";
      count: number;
      title: string;
      words: string;
    }[] = [
      {
        key: "known",
        count: counts.known,
        title: "already in Sales X-Ray",
        words: KEPT_WORDS[duplicates],
      },
      {
        key: "repeat",
        count: counts.repeat,
        title: "repeated in your file",
        words: "added once",
      },
      {
        key: "cant",
        count: counts.cant,
        title: "can't be added",
        words: "no name, phone or email",
      },
    ];
    return (
      <div className={styles.check} data-rows-check="phone">
        <h3 className={styles.ready}>
          <span>{counts.new}</span>{" "}
          {counts.new === 1 ? "new lead is ready" : "new leads are ready"}
        </h3>
        <OutcomeBar rows={rows} />
        <ul className={styles.groups}>
          {groups
            .filter((group) => group.count)
            .map((group) => (
              <li key={group.key} data-check={group.key}>
                <button
                  type="button"
                  className={styles.group}
                  aria-expanded={opened === group.key}
                  onClick={() =>
                    setOpened((now) => (now === group.key ? null : group.key))
                  }
                >
                  <strong data-outcome={group.key}>{group.count}</strong>
                  <span>
                    {group.title}
                    <small>{group.words}</small>
                  </span>
                  {opened === group.key ? (
                    <ChevronDown size={18} aria-hidden="true" />
                  ) : (
                    <ChevronRight size={18} aria-hidden="true" />
                  )}
                </button>
                {opened === group.key ? (
                  <ul className={styles.list}>
                    {rows
                      .filter((row) =>
                        group.key === "cant"
                          ? row.outcome === "bad" || row.outcome === "blank"
                          : row.outcome === group.key,
                      )
                      .slice(0, 50)
                      .map((row) => (
                        <li key={row.row}>
                          <span>
                            Row {row.row + 1} · {row.name || "No name"}
                          </span>
                          <small>
                            {row.outcome === "known" && row.leadName
                              ? `Already here as ${displayName(row.leadName)}`
                              : row.outcome === "repeat" && row.sameAs !== null
                                ? `Same as row ${row.sameAs + 1}`
                                : row.phone}
                          </small>
                        </li>
                      ))}
                  </ul>
                ) : null}
                {group.key === "cant" && download ? (
                  <p className={styles.muted}>
                    These rows go in a file you can fix. {download}
                  </p>
                ) : null}
              </li>
            ))}
        </ul>
        {bad.map((row) => (
          <div key={row.row} className={styles.fixCard} data-fix-row={row.row}>
            <strong>1</strong>
            <span>
              phone looks short
              <small>
                {row.name || `Row ${row.row + 1}`} · {row.phone}
              </small>
            </span>
            <FixPhone row={row} onFix={onFix} />
          </div>
        ))}
        {choice}
      </div>
    );
  }

  const shown = rows.filter((row) =>
    tab === "all"
      ? true
      : tab === "cant"
        ? row.outcome === "bad" || row.outcome === "blank"
        : row.outcome === tab,
  );
  return (
    <div className={styles.check} data-rows-check="computer">
      <h3 className={styles.title}>Here&apos;s what happens to each row</h3>
      <OutcomeBar rows={rows} />
      <div
        className={styles.tiles}
        role="group"
        aria-label="What the file's rows become"
      >
        {tiles.map((tile) => (
          <button
            key={tile.key}
            type="button"
            className={styles.tile}
            data-check={tile.key}
            aria-pressed={tab === tile.key}
            onClick={() =>
              setTab((now) => (now === tile.key ? "all" : tile.key))
            }
          >
            <strong data-outcome={tile.key}>{tile.count}</strong>
            <span>{tile.title}</span>
            {tile.words ? <small>{tile.words}</small> : null}
          </button>
        ))}
      </div>
      {choice}
      <div className={styles.tabs} role="tablist" aria-label="Rows">
        {(
          [
            ["all", "All", rows.length],
            ["new", "New", counts.new],
            ["known", "Already here", counts.known],
            ["repeat", "Repeated", counts.repeat],
            ["cant", "Can't add", counts.cant],
          ] as const
        ).map(([key, words, count]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={styles.tab}
            onClick={() => setTab(key)}
          >
            {words} {count}
          </button>
        ))}
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Row</th>
              <th scope="col">Name</th>
              <th scope="col">Phone</th>
              <th scope="col">City</th>
              <th scope="col">Stage</th>
              <th scope="col">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {shown.slice(0, 200).map((row) => (
              <tr key={row.row} data-outcome={row.outcome}>
                <td>{row.row + 1}</td>
                <td>{row.name || "—"}</td>
                <td data-bad={row.outcome === "bad" ? "" : undefined}>
                  <span>{row.phone || "—"}</span>
                  {row.outcome === "bad" ? (
                    <FixPhone row={row} onFix={onFix} compact />
                  ) : null}
                </td>
                <td>{row.city || "—"}</td>
                <td>{row.stage || "—"}</td>
                <td>
                  <span className={styles.outcome} data-outcome={row.outcome}>
                    {row.outcome === "known" && row.leadName
                      ? `Already here · ${displayName(row.leadName)}`
                      : row.outcome === "repeat" && row.sameAs !== null
                        ? `Repeated · row ${row.sameAs + 1}`
                        : OUTCOME_WORDS[row.outcome]}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length > 200 ? (
        <p className={styles.muted}>The first 200 of {shown.length} rows.</p>
      ) : null}
      {download ? (
        <p className={styles.muted}>
          Rows that can&apos;t be added go in a file you can download.{" "}
          {download}
        </p>
      ) : null}
    </div>
  );
}
