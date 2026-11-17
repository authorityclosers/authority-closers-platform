"use client";

/**
 * Matching a file's columns (owner's picks, 17 Nov 2026; study 01 §5 S2):
 * - I2-A, the default: every column of the file in its own row, with three of its
 *   values, an arrow, where it goes and its state (Matched · Check this match · Not
 *   imported). Rows to check come first. A stage column shows each of its words and the
 *   stage it becomes; a word that is no stage asks which it is.
 * - I2-B, "Advanced": the file itself, with a label over each column to change.
 * - I2-C, the phone: "We matched 8 of your 11 columns · See all", then only the
 *   questions, one at a time ("Question 1 of 2"), with stacked answers.
 *
 * Every column is in exactly one state; nothing here is written until Import. The
 * workspace's earlier choices come back from the server (intake_memory.py) and are
 * marked "From your last import".
 */

import { ArrowDown, ArrowRight, Ban, Check, CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import { Picker } from "../ui/picker";
import { readJourney, type StageView } from "./journey/journey-client";
import { stageName } from "./journey/stage-look";
import {
  FIELD_LABELS,
  type FileCheck,
  type ImportPreview,
  type RepView,
} from "./leads-client";
import styles from "./import-match.module.css";

/** Kept on each lead as a detail (the file's own column name). */
export const KEEP = "_keep";
/** Not imported: its cells are never sent. */
export const SKIP = "_skip";

export const MAPPABLE = [
  "name",
  "phone",
  "email",
  "company",
  "city",
  "language",
  "interest",
];

/** A file's stage and owner columns (owner P0, 23 Oct 2026): names, matched by the server. */
export const COLUMN_LABELS: Record<string, string> = {
  ...FIELD_LABELS,
  stage: "Stage",
  owner: "Owner",
  source: "Source",
  // Old leads kept as history (owner, 2 Nov 2026).
  received: "Enquiry date",
  campaign: "Campaign",
};
/** An old lead's columns: its own day, stage, campaign and salesperson. */
export const HISTORY_COLUMNS = [
  "received",
  "stage",
  "campaign",
  "source",
  "owner",
];

export type ColumnState = "matched" | "check" | "skipped";

export type ColumnRow = {
  header: string;
  samples: string[];
  /** A field, KEEP or SKIP. */
  choice: string;
  state: ColumnState;
  /** Why it's to check, or how it was matched. */
  note: string | null;
  empty: boolean;
  remembered: boolean;
};

export type Question =
  | { kind: "need"; id: string }
  | { kind: "column"; id: string; header: string; samples: string[] }
  | { kind: "stage"; id: string; header: string; word: string; rows: number }
  | { kind: "owner"; id: string; header: string; name: string; rows: number };

export type MatchState = {
  preview: ImportPreview;
  mapping: Record<string, string>;
  /** Headers not imported. */
  skip: readonly string[];
  /** Columns the importer has looked at and answered (no longer "to check"). */
  answered: readonly string[];
  check: FileCheck | null;
  stagePicks: Record<string, string>;
  /** A name and the teammate it is; "" answered as "nobody: the lead rules". */
  ownerPicks: Record<string, string>;
  history: boolean;
  canManage: boolean;
};

/** Up to three of a column's values, to see it is the right one. */
export function samplesOf(
  preview: ImportPreview,
  header: string | undefined,
  count = 3,
): string[] {
  if (!header) return [];
  const seen: string[] = [];
  for (const row of preview.rows) {
    const value = row[header]?.trim();
    if (value && !seen.includes(value)) seen.push(value);
    if (seen.length >= count) break;
  }
  return seen;
}

/** A day as files write it: 02/11/2026, 2026-11-02, 2.11.26. */
const DATE = /^\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}/;

/** Most of these values read as phone numbers (8 to 15 digits, never a date). */
export function looksLikePhones(values: readonly string[]): boolean {
  const phones = values.filter((value) => {
    if (/[a-z]/i.test(value) || DATE.test(value.trim())) return false;
    const digits = value.replace(/\D/g, "").length;
    return digits >= 8 && digits <= 15;
  });
  return values.length > 0 && phones.length * 2 > values.length;
}

/** A row number column ("Sr No", "S.No.", "Sl No"): not imported unless chosen. */
export function isSerialColumn(header: string): boolean {
  const key = header
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  return /^(sr|s|sl|serial|row|index)(_?no|_?number)?$|^(no|#)$/.test(key);
}

/** The fields a column may fill here. */
export function fieldsFor(history: boolean, canManage: boolean): string[] {
  return history
    ? [...MAPPABLE, ...HISTORY_COLUMNS]
    : [...MAPPABLE, "stage", "source", ...(canManage ? ["owner"] : [])];
}

export function fieldLabel(field: string, history: boolean): string {
  if (field === KEEP) return "Keep on the lead";
  if (field === SKIP) return "Don't import";
  if (history && field === "owner") return "Salesperson";
  return COLUMN_LABELS[field] ?? field;
}

/** The stage words no stage was found or picked for. */
export function openStageWords(state: MatchState) {
  return (state.check?.stages ?? []).filter(
    (item) => !item.stage && !state.stagePicks[item.word],
  );
}

/** The owner names that are nobody on the team, not yet answered. */
export function openOwnerNames(state: MatchState) {
  if (state.history) return [];
  return (state.check?.owners ?? []).filter(
    (owner) => !owner.person_id && !(owner.name in state.ownerPicks),
  );
}

/** Every column of the file, in one state each, rows to check first. */
export function columnRows(match: MatchState): ColumnRow[] {
  const { preview, mapping, skip, answered } = match;
  const byHeader = new Map<string, string>();
  for (const [field, header] of Object.entries(mapping))
    if (header) byHeader.set(header, field);
  const remembered = new Set(preview.remembered ?? []);
  const openStages = openStageWords(match);
  const openOwners = openOwnerNames(match);
  const rows = preview.headers.map((header): ColumnRow => {
    const samples = samplesOf(preview, header);
    const empty = samples.length === 0;
    const choice =
      byHeader.get(header) ?? (skip.includes(header) ? SKIP : KEEP);
    const fromMemory = remembered.has(header);
    let state: ColumnState = "matched";
    let note: string | null = fromMemory ? "From your last import" : null;
    if (choice === SKIP || empty) {
      state = "skipped";
      if (empty) note = "Empty in this file";
    } else if (choice === "stage" && openStages.length) {
      state = "check";
      note =
        openStages.length === 1
          ? `"${openStages[0].word}" isn't one of your stages. Choose one.`
          : `${openStages.length} values aren't your stages. Choose them.`;
    } else if (choice === "owner" && openOwners.length) {
      state = "check";
      note =
        openOwners.length === 1
          ? `Nobody on your team is called "${openOwners[0].name}".`
          : `${openOwners.length} names aren't on your team.`;
    } else if (
      choice === KEEP &&
      !fromMemory &&
      !answered.includes(header) &&
      Boolean(mapping.phone) &&
      mapping.phone !== header &&
      looksLikePhones(samples)
    ) {
      state = "check";
      note = "Looks like a second phone number. It stays on the lead.";
    }
    return {
      header,
      samples,
      choice,
      state,
      note,
      empty,
      remembered: fromMemory,
    };
  });
  const order: Record<ColumnState, number> = {
    check: 0,
    matched: 1,
    skipped: 2,
  };
  return rows
    .map((row, index) => ({ row, index }))
    .sort(
      (a, b) => order[a.row.state] - order[b.row.state] || a.index - b.index,
    )
    .map((item) => item.row);
}

export function tally(rows: readonly ColumnRow[]) {
  return {
    matched: rows.filter((row) => row.state === "matched").length,
    check: rows.filter((row) => row.state === "check").length,
    skipped: rows.filter((row) => row.state === "skipped").length,
  };
}

/** The phone's questions (I2-C): only what the import can't decide alone. */
export function questionsOf(match: MatchState): Question[] {
  const out: Question[] = [];
  if (!match.mapping.name && !match.mapping.phone)
    out.push({ kind: "need", id: "need" });
  for (const row of columnRows(match)) {
    if (row.state !== "check") continue;
    if (row.choice === "stage") {
      for (const item of openStageWords(match))
        out.push({
          kind: "stage",
          id: `stage:${item.word}`,
          header: row.header,
          word: item.word,
          rows: item.rows,
        });
    } else if (row.choice === "owner") {
      for (const owner of openOwnerNames(match))
        out.push({
          kind: "owner",
          id: `owner:${owner.name}`,
          header: row.header,
          name: owner.name,
          rows: owner.rows,
        });
    } else {
      out.push({
        kind: "column",
        id: `column:${row.header}`,
        header: row.header,
        samples: row.samples,
      });
    }
  }
  return out;
}

/** The pipeline's stages, for "Which stage is it?". */
export function useImportStages(on: boolean, pipeline: string) {
  const [stages, setStages] = useState<StageView[] | null>(null);
  useEffect(() => {
    if (!on) return;
    let live = true;
    readJourney(pipeline || undefined).then(
      (next) => {
        if (live) setStages(next.stages.filter((stage) => !stage.archived));
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [on, pipeline]);
  return stages;
}

export type MatchProps = {
  match: MatchState;
  stages: StageView[] | null;
  side: "live" | "cold" | "history";
  /** Everyone on the team, for "Who is 'Rohit P'?". */
  people: RepView[] | null;
  onColumn: (header: string, choice: string) => void;
  onStage: (word: string, stage: string) => void;
  onOwner: (name: string, person: string) => void;
};

const STATE_WORDS: Record<ColumnState, string> = {
  matched: "Matched",
  check: "Check this match",
  skipped: "Not imported",
};

function StateMark({ row }: { row: ColumnRow }) {
  const Icon =
    row.state === "matched" ? Check : row.state === "check" ? CircleAlert : Ban;
  return (
    <span className={styles.state} data-state={row.state}>
      <Icon size={16} strokeWidth={2.4} aria-hidden="true" />
      {row.choice === "stage" && row.state === "check"
        ? "Check values"
        : row.choice === KEEP && row.state === "matched"
          ? "Kept on the lead"
          : STATE_WORDS[row.state]}
    </span>
  );
}

function ColumnPick({
  row,
  match,
  onColumn,
  compact = false,
}: {
  row: ColumnRow;
  match: MatchState;
  onColumn: MatchProps["onColumn"];
  compact?: boolean;
}) {
  const options = [
    ...fieldsFor(match.history, match.canManage).map((field) => ({
      key: field,
      label: fieldLabel(field, match.history),
    })),
    { key: KEEP, label: fieldLabel(KEEP, match.history) },
    { key: SKIP, label: fieldLabel(SKIP, match.history) },
  ];
  return (
    <Picker
      title={`Where "${row.header}" goes`}
      ariaLabel={`Where ${row.header} goes`}
      mode={compact ? "cell" : "auto"}
      value={row.choice}
      options={options}
      onChange={(key) => onColumn(row.header, key ?? KEEP)}
      className={compact ? styles.chipPick : styles.pick}
    />
  );
}

/** A stage column's words and the stage each becomes, with a chooser for the rest. */
function StageWords({
  match,
  stages,
  side,
  onStage,
}: Pick<MatchProps, "match" | "stages" | "side" | "onStage">) {
  const words = match.check?.stages ?? [];
  if (!words.length) return null;
  const options = (stages ?? []).map((stage) => ({
    key: stage.key,
    label: stageName(stage, side === "cold" ? "cold" : "inbound"),
  }));
  return (
    <ul className={styles.values} aria-label="The file's stage words">
      {words.slice(0, 12).map((item) => {
        const picked = match.stagePicks[item.word];
        const label = picked
          ? (options.find((option) => option.key === picked)?.label ?? picked)
          : (item.label ?? item.stage);
        return (
          <li
            key={item.word}
            data-open={!item.stage && !picked ? "" : undefined}
          >
            <span className={styles.word}>{item.word}</span>
            <ArrowRight size={12} aria-hidden="true" />
            {item.stage && !picked ? (
              <span className={styles.becomes}>
                {label}
                {item.remembered ? " · last import" : ""}
              </span>
            ) : (
              <Picker
                title={`Which stage is "${item.word}"?`}
                ariaLabel={`Stage for ${item.word}`}
                mode="cell"
                value={picked ?? null}
                placeholder="Choose a stage"
                options={options}
                onChange={(key) => key && onStage(item.word, key)}
                className={styles.valuePick}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** An owner column's names that aren't on the team, each with a chooser. */
function OwnerNames({
  match,
  people,
  onOwner,
}: Pick<MatchProps, "match" | "people" | "onOwner">) {
  const strangers = (match.check?.owners ?? []).filter(
    (owner) => !owner.person_id,
  );
  if (!strangers.length || match.history) return null;
  const options = [
    ...(people ?? []).map((rep) => ({
      key: rep.person_id,
      label: displayName(rep.name),
    })),
    { key: "", label: "Nobody: share by my lead rules" },
  ];
  return (
    <ul className={styles.values} aria-label="Names not on your team">
      {strangers.slice(0, 12).map((owner) => {
        const picked = match.ownerPicks[owner.name];
        return (
          <li
            key={owner.name}
            data-open={picked === undefined ? "" : undefined}
          >
            <span className={styles.word}>{owner.name}</span>
            <ArrowRight size={12} aria-hidden="true" />
            <Picker
              title={`Who is "${owner.name}"?`}
              ariaLabel={`Teammate for ${owner.name}`}
              mode="cell"
              value={picked ?? null}
              placeholder="Choose who"
              options={options}
              onChange={(key) => onOwner(owner.name, key ?? "")}
              className={styles.valuePick}
            />
          </li>
        );
      })}
    </ul>
  );
}

/** The counts as three chips: "8 matched · 2 to check · 1 not imported". */
export function MatchCounts({ rows }: { rows: readonly ColumnRow[] }) {
  const counts = tally(rows);
  return (
    <div className={styles.counts} data-match-counts="">
      <span data-state="matched">{counts.matched} matched</span>
      {counts.check ? (
        <span data-state="check">{counts.check} to check</span>
      ) : null}
      {counts.skipped ? (
        <span data-state="skipped">{counts.skipped} not imported</span>
      ) : null}
    </div>
  );
}

/** I2-A: one row per column of the file (laptop), stacked cards on a phone. */
export function MatchPairs(props: MatchProps) {
  const { match, onColumn } = props;
  const rows = columnRows(match);
  return (
    <ol className={styles.pairs} aria-label="Your columns">
      {rows.map((row) => (
        <li
          key={row.header}
          className={styles.pair}
          data-state={row.state}
          data-column={row.header}
        >
          <div className={styles.from}>
            <small className={styles.inFile}>In your file</small>
            <strong>{row.header}</strong>
            <span className={styles.samples} data-samples={row.header}>
              {row.samples.join(" · ") || "Empty in this file"}
            </span>
          </div>
          <ArrowRight
            size={18}
            aria-hidden="true"
            className={styles.arrowSide}
          />
          <ArrowDown
            size={18}
            aria-hidden="true"
            className={styles.arrowDown}
          />
          <div className={styles.to}>
            <small className={styles.inFile}>Goes to</small>
            <ColumnPick row={row} match={match} onColumn={onColumn} />
            {row.choice === "stage" ? (
              <StageWords
                match={match}
                stages={props.stages}
                side={props.side}
                onStage={props.onStage}
              />
            ) : null}
            {row.choice === "owner" ? (
              <OwnerNames
                match={match}
                people={props.people}
                onOwner={props.onOwner}
              />
            ) : null}
          </div>
          <div className={styles.status}>
            <StateMark row={row} />
            {row.note ? <small>{row.note}</small> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** I2-B ("Advanced"): the file's first rows with a label over each column. */
export function MatchSheet(props: MatchProps) {
  const { match, onColumn } = props;
  const rows = columnRows(match);
  const byHeader = new Map(rows.map((row) => [row.header, row]));
  const headers = match.preview.headers;
  return (
    <div className={styles.sheetWrap}>
      <table
        className={styles.sheet}
        aria-label="Your file, with a label on each column"
      >
        <thead>
          <tr>
            {headers.map((header) => {
              const row = byHeader.get(header)!;
              return (
                <th key={header} data-state={row.state} scope="col">
                  <div className={styles.label} data-state={row.state}>
                    <ColumnPick
                      row={row}
                      match={match}
                      onColumn={onColumn}
                      compact
                    />
                  </div>
                  <span className={styles.head}>{header}</span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {match.preview.rows.slice(0, 6).map((line, index) => (
            <tr key={index}>
              {headers.map((header) => (
                <td key={header} data-state={byHeader.get(header)?.state}>
                  {line[header] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One of the phone's questions (I2-C), with its answers stacked. */
export function MatchQuestion({
  question,
  props,
  onAnswered,
}: {
  question: Question;
  props: MatchProps;
  onAnswered: (header: string) => void;
}) {
  const { match, stages, side, people, onColumn, onStage, onOwner } = props;
  if (question.kind === "need") {
    return (
      <div className={styles.question}>
        <h3>Which column has the name or the phone number?</h3>
        <div className={styles.answers}>
          {match.preview.headers.slice(0, 12).map((header) => (
            <button
              key={header}
              type="button"
              className={styles.answer}
              onClick={() => onColumn(header, "name")}
            >
              {header}
              <small>{samplesOf(match.preview, header, 2).join(" · ")}</small>
            </button>
          ))}
        </div>
      </div>
    );
  }
  if (question.kind === "stage") {
    return (
      <div className={styles.question}>
        <h3>
          {`Your '${question.header}' column says '${question.word}'. Which stage is it?`}
        </h3>
        <p className={styles.muted}>
          {question.rows} {question.rows === 1 ? "lead" : "leads"} · We&apos;ll
          remember this for your next import.
        </p>
        <div className={styles.stageChips} role="group" aria-label="Stages">
          {(stages ?? []).map((stage) => {
            const on = match.stagePicks[question.word] === stage.key;
            return (
              <button
                key={stage.key}
                type="button"
                className={styles.chip}
                aria-pressed={on}
                onClick={() => onStage(question.word, stage.key)}
              >
                {on ? <Check size={14} aria-hidden="true" /> : null}
                {stageName(stage, side === "cold" ? "cold" : "inbound")}
              </button>
            );
          })}
        </div>
      </div>
    );
  }
  if (question.kind === "owner") {
    const picked = match.ownerPicks[question.name];
    return (
      <div className={styles.question}>
        <h3>Who is &apos;{question.name}&apos; in your team?</h3>
        <p className={styles.muted}>
          {question.rows} {question.rows === 1 ? "lead" : "leads"} · We&apos;ll
          remember this for your next import.
        </p>
        <div className={styles.answers}>
          {(people ?? []).map((rep) => (
            <button
              key={rep.person_id}
              type="button"
              className={styles.answer}
              aria-pressed={picked === rep.person_id}
              onClick={() => onOwner(question.name, rep.person_id)}
            >
              {picked === rep.person_id ? (
                <Check size={16} aria-hidden="true" />
              ) : null}
              {displayName(rep.name)}
            </button>
          ))}
          <button
            type="button"
            className={styles.answer}
            aria-pressed={picked === ""}
            onClick={() => onOwner(question.name, "")}
          >
            Nobody: share by my lead rules
          </button>
        </div>
      </div>
    );
  }
  const row = columnRows(match).find((item) => item.header === question.header);
  return (
    <div className={styles.question}>
      <h3>What is in &apos;{question.header}&apos;?</h3>
      <p className={styles.muted}>{question.samples.join(" · ")}</p>
      <div className={styles.answers}>
        <button
          type="button"
          className={styles.answer}
          aria-pressed={
            row?.choice === KEEP && match.answered.includes(question.header)
          }
          onClick={() => {
            onColumn(question.header, KEEP);
            onAnswered(question.header);
          }}
        >
          A second phone number
          <small>Kept on the lead</small>
        </button>
        <div className={styles.answerPick}>
          <span>Something else</span>
          {row ? (
            <ColumnPick
              row={row}
              match={match}
              onColumn={(header, choice) => {
                onColumn(header, choice);
                onAnswered(header);
              }}
            />
          ) : null}
        </div>
        <button
          type="button"
          className={styles.answer}
          aria-pressed={row?.choice === SKIP}
          onClick={() => {
            onColumn(question.header, SKIP);
            onAnswered(question.header);
          }}
        >
          Don&apos;t import it
        </button>
      </div>
    </div>
  );
}

/** I2-C's head card: "We matched 8 of your 11 columns · See all". */
export function MatchedCard({
  rows,
  open,
  onToggle,
}: {
  rows: readonly ColumnRow[];
  open: boolean;
  onToggle: () => void;
}) {
  const counts = tally(rows);
  const matched = rows.filter(
    (row) => row.state === "matched" && row.choice !== KEEP,
  );
  return (
    <div className={styles.matched} data-match-card="">
      <p>
        <Check size={18} strokeWidth={2.6} aria-hidden="true" />
        <strong>
          We matched {counts.matched} of your {rows.length} columns
        </strong>
        <button type="button" className={styles.link} onClick={onToggle}>
          {open ? "Hide" : "See all"}
        </button>
      </p>
      {open ? null : (
        <ul className={styles.chips}>
          {matched.slice(0, 8).map((row) => (
            <li key={row.header}>
              {row.header} → {COLUMN_LABELS[row.choice] ?? row.choice}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
