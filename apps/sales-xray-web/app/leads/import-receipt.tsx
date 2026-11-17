"use client";

/**
 * The receipt after Import (owner's pick I4-B, 17 Nov 2026: "perfect"; study 01 §5 S4).
 * It replaces the last step in place: a check, "9 leads imported", where the file came
 * from, who got how many, the stage, then "3 rows not imported" with why and the rows
 * as a file, and Undo this import, saying exactly what Undo removes (only the new leads,
 * never changes to leads already here).
 */

import { Check, Copy, Info, Layers, UserRound, UsersRound } from "lucide-react";

import { displayName } from "../display-name";
import { resultLines, SkippedDownload } from "./import-check";
import { UndoImportButton } from "./import-undo";
import type { Duplicates, ImportPreview, ImportResult } from "./leads-client";
import { PASTED_FILE } from "./paste-import";
import styles from "./import-receipt.module.css";

export function ImportReceipt({
  result,
  preview,
  duplicates,
  stageFromFile,
  onUndone,
}: {
  result: ImportResult;
  preview: ImportPreview;
  duplicates: Duplicates;
  /** The file's own stage column was used. */
  stageFromFile: boolean;
  onUndone: () => void;
}) {
  const created = result.created;
  const lines = resultLines(result, duplicates);
  const notImported = lines.filter(
    (line) => line.key !== "new" && line.key !== "updated" && line.count > 0,
  );
  const notCount = notImported.reduce((sum, line) => sum + line.count, 0);
  const from =
    preview.file_name === PASTED_FILE ? "Pasted rows" : preview.file_name;
  const history = result.side === "history";
  const into = history
    ? "Old leads"
    : result.side === "cold"
      ? "Cold Leads"
      : "Inbound Leads";
  return (
    <div className={styles.receipt} data-import-receipt="">
      <div className={styles.head}>
        <span className={styles.done} aria-hidden="true">
          <Check size={28} strokeWidth={2.6} />
        </span>
        <h3 className={styles.title}>
          {created} {created === 1 ? "lead" : "leads"} imported
        </h3>
        <p className={styles.muted}>
          From {from} · just now · in {into}
        </p>
      </div>
      <ul className={styles.card} aria-label="Who got them">
        {result.given?.map((item) => (
          <li key={item.person_id}>
            <UsersRound size={18} aria-hidden="true" />
            <strong>{displayName(item.name)}</strong>
            <span>
              · {item.leads} {item.leads === 1 ? "lead" : "leads"}
            </span>
          </li>
        ))}
        {result.owned ? (
          <li>
            <UserRound size={18} aria-hidden="true" />
            <strong>Owners from your file</strong>
            <span>
              · {result.owned} {result.owned === 1 ? "lead" : "leads"}
            </span>
          </li>
        ) : null}
        {!history && result.waiting ? (
          <li>
            <UsersRound size={18} aria-hidden="true" />
            <strong>Waiting for an owner</strong>
            <span>
              · {result.waiting} {result.waiting === 1 ? "lead" : "leads"}
            </span>
          </li>
        ) : null}
        <li>
          <Layers size={18} aria-hidden="true" />
          <strong>Stage</strong>
          <span>
            ·{" "}
            {stageFromFile
              ? `from your file${result.staged ? ` (${result.staged})` : ""}`
              : "as you chose"}
          </span>
        </li>
        {result.updated ? (
          <li>
            <Copy size={18} aria-hidden="true" />
            <strong>
              {duplicates === "replace"
                ? "Details replaced"
                : "Details filled in"}
            </strong>
            <span>
              · {result.updated} {result.updated === 1 ? "lead" : "leads"}
            </span>
          </li>
        ) : null}
      </ul>
      {notCount ? (
        <section className={styles.card} aria-labelledby="import-not">
          <h4 id="import-not" className={styles.cardTitle}>
            {notCount} {notCount === 1 ? "row" : "rows"} not imported
          </h4>
          <ul className={styles.why}>
            {notImported.map((line) => (
              <li key={line.key} data-not={line.key}>
                <Info size={16} aria-hidden="true" />
                {line.count}{" "}
                {line.key === "known"
                  ? line.count === 1
                    ? "already a lead"
                    : "already leads"
                  : line.key === "repeat"
                    ? "repeated in your file"
                    : "had no name or a number that can't be read"}
              </li>
            ))}
          </ul>
          <SkippedDownload preview={preview} result={result} />
        </section>
      ) : null}
      {result.import_id && result.undo_until ? (
        <div className={styles.undo}>
          <UndoImportButton importId={result.import_id} onUndone={onUndone} />
          <p className={styles.muted}>
            Removes the {created} new {created === 1 ? "lead" : "leads"}, never
            changes to leads already here. Available for 48 hours in Recent
            imports.
          </p>
        </div>
      ) : null}
    </div>
  );
}
