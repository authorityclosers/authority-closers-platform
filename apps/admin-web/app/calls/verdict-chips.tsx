"use client";

/**
 * Review 2.0 on one analysis item: the pipeline's questions as one-tap chips
 * (Right, Wrong, Unsure), and its follow-up ("What should it say?") once the
 * answer calls for it. Each save is its own audited, idempotent answer; a
 * changed answer supersedes the old one on the server.
 */
import { useState } from "react";

import { command, keyFor, type Intent } from "../lib/client-api";
import {
  normalizeVerdict,
  type ReviewAnswer,
  type ReviewPipelineView,
  type ReviewVerdictView,
} from "./review-verdicts-data";
import styles from "./analysis-tab.module.css";

const OPTION_LABEL: Record<string, string> = {
  correct: "Right",
  wrong: "Wrong",
  unsure: "Unsure",
  true: "True",
  false: "False",
};

/** Pick lists longer than this show as a menu. */
const LONG_PICK = 6;

const label = (option: string) =>
  OPTION_LABEL[option] ?? option.charAt(0).toUpperCase() + option.slice(1);

export function VerdictChips({
  recordingId,
  pipeline,
  targetKind,
  targetRef,
  mine,
  others,
  onSaved,
}: {
  recordingId: string;
  pipeline: ReviewPipelineView;
  targetKind: string;
  targetRef: string;
  mine: Record<string, ReviewAnswer>;
  others: number;
  onSaved: (verdict: ReviewVerdictView) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [intents, setIntents] = useState<Record<string, Intent>>({});

  const save = async (question: string, answer: ReviewAnswer) => {
    const body = {
      pipeline: pipeline.key,
      target_kind: targetKind,
      target_ref: targetRef,
      question,
      answer,
    };
    const intent = keyFor(intents[question] ?? null, body);
    setIntents((current) => ({ ...current, [question]: intent }));
    setBusy(question);
    setError(null);
    const result = await command<unknown>(
      `/v1/admin/conversation/review/calls/${recordingId}/verdicts`,
      body,
      intent.key,
    );
    setBusy(null);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    onSaved(normalizeVerdict(result.data));
  };

  const shown = pipeline.questions.filter((question) =>
    Object.entries(question.when).every(
      ([key, value]) => mine[key]?.value === value,
    ),
  );

  return (
    <span className={styles.review} aria-label={`Review: ${pipeline.title}`}>
      {shown.map((question) =>
        // A long pick list (the engine's 16 intents) is a menu, not a row of chips.
        question.kind === "pick" && question.options.length > LONG_PICK ? (
          <select
            key={question.key}
            className={styles.pick}
            aria-label={question.label}
            value={String(mine[question.key]?.value ?? "")}
            disabled={busy !== null}
            onChange={(event) => {
              if (event.target.value)
                void save(question.key, { value: event.target.value });
            }}
          >
            <option value="">{question.label}</option>
            {question.options.map((option) => (
              <option key={option} value={option}>
                {label(option).replaceAll("_", " ")}
              </option>
            ))}
          </select>
        ) : question.kind === "verdict" || question.kind === "pick" ? (
          <span
            key={question.key}
            className={styles.chips}
            role="group"
            aria-label={question.label}
          >
            {question.options.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={mine[question.key]?.value === option}
                disabled={busy !== null}
                onClick={() => void save(question.key, { value: option })}
              >
                {label(option)}
              </button>
            ))}
          </span>
        ) : question.kind === "scale" ? (
          <span
            key={question.key}
            className={styles.chips}
            role="group"
            aria-label={question.label}
            title={question.label}
          >
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={mine[question.key]?.value === value}
                aria-label={`${question.label} ${value} of 5`}
                disabled={busy !== null}
                onClick={() => void save(question.key, { value })}
              >
                {value}
              </button>
            ))}
          </span>
        ) : question.kind === "correct" ? (
          <span key={question.key} className={styles.fix}>
            <input
              aria-label={question.label}
              placeholder={question.label}
              maxLength={2000}
              value={drafts[question.key] ?? mine[question.key]?.text ?? ""}
              onChange={(event) =>
                setDrafts((current) => ({
                  ...current,
                  [question.key]: event.target.value,
                }))
              }
            />
            <button
              type="button"
              disabled={
                busy !== null ||
                !(drafts[question.key] ?? "").trim() ||
                drafts[question.key] === mine[question.key]?.text
              }
              onClick={() =>
                void save(question.key, { text: drafts[question.key] ?? "" })
              }
            >
              {busy === question.key ? "Saving…" : "Save"}
            </button>
          </span>
        ) : null,
      )}
      {others ? (
        <small className={styles.others}>
          {others} other {others === 1 ? "reviewer" : "reviewers"}
        </small>
      ) : null}
      {error ? (
        <small className={styles.error} role="alert">
          {error}
        </small>
      ) : null}
    </span>
  );
}
