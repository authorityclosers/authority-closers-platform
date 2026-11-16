"use client";

/**
 * A file of new leads in the import's Check step (owner's import study, 16 Nov 2026):
 * - each stage word in the file and the stage it becomes; a word that is no stage here
 *   is counted and said, with the stage it starts in, and the word stays on the lead;
 * - the owners the file names: rows naming a teammate keep that teammate, and only the
 *   rest are shared ("Share between my sellers" never overrides the file);
 * - every column: matched, kept on each lead as a detail, empty, or not imported.
 * Nothing is written until Import.
 */

import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import {
  checkFile,
  LeadsError,
  type FileCheck,
  type ImportPreview,
} from "./leads-client";
import styles from "./import-check.module.css";

export type FileCheckState = {
  check: FileCheck | null;
  error: string | null;
};

export function useFileCheck({
  on,
  preview,
  mapping,
  side,
  step,
  pipeline,
}: {
  /** New leads (not Old leads), on the Check or Assign step. */
  on: boolean;
  preview: ImportPreview | null;
  mapping: Record<string, string>;
  side: "live" | "cold";
  step: string;
  pipeline: string;
}): FileCheckState {
  const [check, setCheck] = useState<FileCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!on || !preview) return;
    const controller = new AbortController();
    checkFile(
      preview,
      mapping,
      side,
      step,
      pipeline || null,
      controller.signal,
    ).then(
      (next) => {
        setCheck(next);
        setError(null);
      },
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setError(
          reason instanceof LeadsError
            ? reason.message
            : "The file couldn't be checked.",
        );
      },
    );
    return () => controller.abort();
  }, [on, preview, mapping, side, step, pipeline]);
  return { check, error };
}

/** New leads that keep an owner the file names: only the rest are shared. */
export const ownedByFile = (state: FileCheckState): number =>
  state.check?.owned_new ?? 0;

/** "Rohan Patil 3 · Farah Shaikh 2": the teammates the file names, by rows. */
export function fileOwnersLine(check: FileCheck | null): string {
  return (check?.owners ?? [])
    .filter((owner) => owner.person_id)
    .map(
      (owner) =>
        `${displayName(owner.person_name ?? owner.name)} ${owner.rows}`,
    )
    .join(" · ");
}

const list = (items: string[]) => items.join(", ");

/** The Check step's lines for the file's stages, owners and columns. */
export function FileCheckLines({
  state,
  stageColumn,
}: {
  state: FileCheckState;
  /** The file's column read as the stage ("Status"). */
  stageColumn?: string;
}) {
  const { check, error } = state;
  if (error)
    return (
      <p className={styles.help} role="status">
        {error}
      </p>
    );
  if (!check)
    return (
      <p className={styles.help} role="status">
        Checking the file…
      </p>
    );
  const unplaced = check.stages.filter((item) => !item.stage);
  const unplacedRows = unplaced.reduce((sum, item) => sum + item.rows, 0);
  const strangers = check.owners.filter((owner) => !owner.person_id);
  const by = (fate: FileCheck["columns"][number]["fate"]) =>
    check.columns.filter((column) => column.fate === fate);
  const matched = by("matched");
  const kept = by("kept");
  const empty = by("empty");
  const hidden = by("not_imported");
  const owners = fileOwnersLine(check);
  return (
    <>
      {check.stages.length ? (
        <dl
          className={styles.counts}
          aria-label="The file's stages"
          data-file-check="stages"
        >
          {check.stages.map((item) => (
            <div key={item.word} data-stage-matched={item.stage ? "" : "no"}>
              <dt>
                {item.word} →{" "}
                {item.stage
                  ? (item.label ?? item.stage)
                  : `no stage by that name: starts in ${check.unmatched_stage ?? "the first stage"}`}
              </dt>
              <dd>{item.rows}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {unplacedRows ? (
        <p className={styles.help} data-file-check="unplaced">
          {unplacedRows === 1
            ? "1 lead's stage isn't one of your stages"
            : `${unplacedRows} leads' stages aren't among your stages`}
          : the file&apos;s word stays on each lead
          {stageColumn ? `, under ${stageColumn}` : ""}.
        </p>
      ) : null}
      {owners || strangers.length ? (
        <p className={styles.help} data-file-check="owners">
          {owners ? `Owners from your file keep their leads: ${owners}.` : ""}
          {strangers.length
            ? `${owners ? " " : ""}Nobody on your team called ${list(
                strangers.map((owner) => owner.name),
              )}: those rows go the way you pick under Assign.`
            : ""}
        </p>
      ) : null}
      <p className={styles.help} data-file-check="columns">
        {`Your ${check.columns.length} columns: ${matched.length} matched`}
        {kept.length
          ? ` · ${kept.length} kept on each lead as details (${list(kept.map((column) => column.header))})`
          : ""}
        {empty.length
          ? ` · ${empty.length} empty, so not imported (${list(empty.map((column) => column.header))})`
          : ""}
        {hidden.length
          ? ` · ${hidden.length} not imported: another app's ids (${list(hidden.map((column) => column.header))})`
          : ""}
        .
      </p>
    </>
  );
}
