"use client";

/**
 * The import's check (competitor teardown 5, 1 Nov 2026): what the file's rows become, each
 * count with its reason, before anything is written; what happens to a row whose number is
 * already a lead (Skip, Fill blanks or Replace); and after the import, the rows it didn't
 * use, with why, as a file to fix and import again.
 */

import { csvCell } from "../csv-export";
import type {
  Duplicates,
  ImportPreview,
  ImportResult,
  ImportSkip,
} from "./leads-client";
import styles from "./import-check.module.css";

/** The file's rows by what the import does with them; the zero ones are left out. */
export function checkLines(
  preview: ImportPreview,
  fresh: number,
): { key: string; label: string; count: number }[] {
  const bad = preview.bad_numbers ?? 0;
  const blank = Math.max(
    0,
    preview.total_rows - (preview.importable ?? preview.total_rows) - bad,
  );
  return [
    { key: "new", label: "New leads", count: fresh },
    { key: "known", label: "Already leads", count: preview.known_leads ?? 0 },
    {
      key: "repeat",
      label: "Repeated in the file",
      count: preview.repeats_in_file,
    },
    // Said as skipped, never a silent drop (orchestrator, 2 Nov 2026).
    { key: "bad", label: "Skipped: number can't be read", count: bad },
    { key: "blank", label: "Skipped: no name, phone or email", count: blank },
  ].filter((line) => line.key === "new" || line.count > 0);
}

const CHOICES: { key: Duplicates; label: string; words: string }[] = [
  { key: "skip", label: "Skip", words: "They stay as they are." },
  {
    key: "fill",
    label: "Fill blanks",
    words:
      "Their empty details are filled from the file. Their stage and owner stay.",
  },
  {
    key: "replace",
    label: "Replace",
    words:
      "Their name and details become the file's where the file has them. This can't be undone; each lead's history keeps what was there.",
  },
];

/** The Check step: counts with reasons, and (owners and admins) the choice for numbers
 *  already leads. Skip is the default; Fill blanks and Replace say what they change. */
export function ImportCheck({
  preview,
  fresh,
  canManage,
  duplicates,
  onDuplicates,
}: {
  preview: ImportPreview;
  fresh: number;
  canManage: boolean;
  duplicates: Duplicates;
  onDuplicates: (next: Duplicates) => void;
}) {
  const known = preview.known_leads ?? 0;
  const chosen = CHOICES.find((item) => item.key === duplicates) ?? CHOICES[0];
  return (
    <div className={styles.check}>
      <dl className={styles.counts} aria-label="What the file's rows become">
        {checkLines(preview, fresh).map((line) => (
          <div key={line.key} data-check={line.key}>
            <dt>{line.label}</dt>
            <dd>{line.count}</dd>
          </div>
        ))}
      </dl>
      {known && canManage ? (
        <div className={styles.choice}>
          <span className={styles.label} aria-hidden="true">
            {known === 1
              ? "1 number is already a lead"
              : `${known} numbers are already leads`}
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
          <p
            className={chosen.key === "skip" ? styles.help : styles.warning}
            data-duplicates={chosen.key}
          >
            {chosen.words}
          </p>
        </div>
      ) : known ? (
        <p className={styles.help}>Numbers already leads stay as they are.</p>
      ) : null}
    </div>
  );
}

/** What the import did with the file's rows, in the check's words, so the lines add up
 *  to the rows; an answer without reasons (an older server) says what it can. */
export function resultLines(
  result: ImportResult,
  duplicates: Duplicates,
): { key: string; label: string; count: number }[] {
  const reasons = result.skipped_rows;
  const updated = result.updated ?? 0;
  if (!reasons)
    return [
      { key: "new", label: "New leads", count: result.created },
      { key: "known", label: "Already leads", count: result.repeats },
      { key: "left", label: "Skipped", count: result.skipped },
    ].filter((line) => line.key !== "left" || line.count > 0);
  const known = reasons.filter((item) =>
    item.reason.startsWith("Already a lead"),
  ).length;
  const repeated = reasons.filter(
    (item) => item.reason === "Repeated in the file",
  ).length;
  return [
    { key: "new", label: "New leads", count: result.created },
    { key: "known", label: "Already leads", count: known + updated },
    {
      key: "updated",
      label:
        duplicates === "replace" ? "Details replaced" : "Details filled in",
      count: updated,
    },
    { key: "repeat", label: "Repeated in the file", count: repeated },
    {
      key: "left",
      label: "Skipped",
      count: reasons.length - known - repeated,
    },
  ].filter(
    (line) => line.key === "new" || line.key === "known" || line.count > 0,
  );
}

// A phone number ("+91 98760 …") can't run as a formula: it stays as written, without
// the guard's apostrophe, so the fixed file imports again as it was.
const PHONE = /^\+[\d\s()-]+$/;

/** The rows an import didn't use as a CSV: the file's own columns, then why. */
export function skippedCsv(
  preview: ImportPreview,
  skipped: readonly ImportSkip[],
): string {
  const sorted = [...skipped].sort((a, b) => a.row - b.row);
  const cell = (value: string) =>
    PHONE.test(value) ? `"${value}"` : csvCell(value);
  return [
    [...preview.headers, "Reason"],
    ...sorted.map((item) => [
      ...preview.headers.map(
        (header) => preview.rows[item.row]?.[header] ?? "",
      ),
      item.reason,
    ]),
  ]
    .map((row) => row.map(cell).join(","))
    .join("\n");
}

/** "Download rows not added (with reason)" on the import's result: every row that made no
 *  lead and changed none (skipped, already leads, repeats); nothing when none. */
export function SkippedDownload({
  preview,
  result,
}: {
  preview: ImportPreview;
  result: ImportResult;
}) {
  const skipped = result.skipped_rows ?? [];
  if (!skipped.length) return null;
  const base = preview.file_name.replace(/\.[a-z0-9]+$/i, "") || "import";
  return (
    <a
      className={styles.download}
      href={`data:text/csv;charset=utf-8,${encodeURIComponent(skippedCsv(preview, skipped))}`}
      download={`${base}-skipped-rows.csv`}
    >
      Download rows not added ({skipped.length}, with reason)
    </a>
  );
}
