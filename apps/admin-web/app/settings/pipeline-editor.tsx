"use client";

/**
 * Edit one Review 2.0 pipeline (owner 19 Oct: configurable pipelines built on
 * primitives): its title, how many calls a sample takes, and its questions.
 * Each question is one "ask": a verdict, a pick, a correction or a 1–5 scale,
 * asked always or only after an earlier answer. Saving makes a new version;
 * answers keep the version they were given under. What is judged, what is
 * shown, reconcile and measure are listed but not edited yet.
 */
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import type { ReviewQuestion } from "../calls/review-verdicts-data";
import { command, keyFor, type Intent } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import {
  KIND_LABEL,
  draftProblems,
  newQuestionKey,
  optionsFromText,
  pipelineRequest,
  type PipelineLimits,
  type PipelineSetting,
  type QuestionKind,
} from "./review-pipelines-data";
import styles from "./pipeline-editor.module.css";

type Draft = {
  title: string;
  sampleLimit: number;
  questions: ReviewQuestion[];
};

const fromPipeline = (pipeline: PipelineSetting): Draft => ({
  title: pipeline.title,
  sampleLimit: pipeline.sampleLimit,
  questions: pipeline.questions.map((item) => ({ ...item })),
});

const hasOptions = (kind: QuestionKind) =>
  kind === "verdict" || kind === "pick";

export function PipelineEditor({
  pipeline,
  limits,
  canEdit,
}: {
  pipeline: PipelineSetting;
  limits: PipelineLimits;
  canEdit: boolean;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(() => fromPipeline(pipeline));
  // Options are typed as text and read on each change, so a comma can be typed.
  const [optionText, setOptionText] = useState<string[]>(() =>
    pipeline.questions.map((item) => item.options.join(", ")),
  );
  const [state, setState] = useState<"idle" | "saving">("idle");
  const [message, setMessage] = useState<{
    tone: "good" | "bad";
    text: string;
  } | null>(null);
  const intent = useRef<Intent | null>(null);

  const original = JSON.stringify(fromPipeline(pipeline));
  const changed = JSON.stringify(draft) !== original;
  const problems = changed ? draftProblems(draft, limits) : [];

  const update = (index: number, patch: Partial<ReviewQuestion>) =>
    setDraft((current) => ({
      ...current,
      questions: current.questions.map((item, at) =>
        at === index ? { ...item, ...patch } : item,
      ),
    }));

  const move = (index: number, by: -1 | 1) => {
    const swap = <T,>(list: T[]) => {
      const next = [...list];
      [next[index], next[index + by]] = [next[index + by], next[index]];
      return next;
    };
    setDraft((current) => ({ ...current, questions: swap(current.questions) }));
    setOptionText(swap);
  };

  const remove = (index: number) => {
    const gone = draft.questions[index]?.key;
    setDraft((current) => ({
      ...current,
      questions: current.questions
        .filter((_, at) => at !== index)
        // A question that followed the removed one is now asked always.
        .map((item) =>
          gone && gone in item.when ? { ...item, when: {} } : item,
        ),
    }));
    setOptionText((current) => current.filter((_, at) => at !== index));
  };

  const add = () => {
    setDraft((current) => ({
      ...current,
      questions: [
        ...current.questions,
        {
          key: newQuestionKey(current.questions),
          kind: "pick",
          label: "",
          options: [],
          when: {},
        },
      ],
    }));
    setOptionText((current) => [...current, ""]);
  };

  const save = async () => {
    if (!changed || problems.length || state === "saving") return;
    const body = pipelineRequest(pipeline.version, draft);
    intent.current = keyFor(intent.current, body);
    setState("saving");
    setMessage(null);
    const result = await command<{ version?: number; changed?: boolean }>(
      `/v1/admin/conversation/review/pipelines/${encodeURIComponent(pipeline.key)}`,
      body,
      intent.current.key,
    );
    setState("idle");
    if (!result.ok) {
      setMessage({ tone: "bad", text: result.message });
      return;
    }
    setMessage({
      tone: "good",
      text:
        result.data.changed === false
          ? "Nothing changed."
          : `Saved as version ${result.data.version ?? pipeline.version + 1}. New answers use it.`,
    });
    router.refresh();
  };

  const disabled = !canEdit || state === "saving";

  return (
    <div className={styles.editor}>
      <div className={styles.row}>
        <label className={styles.field}>
          <span>Title</span>
          <input
            value={draft.title}
            maxLength={limits.label}
            disabled={disabled}
            onChange={(event) =>
              setDraft((current) => ({ ...current, title: event.target.value }))
            }
          />
        </label>
        <label className={styles.field} data-narrow="">
          <span>Calls a sample</span>
          <input
            type="number"
            min={1}
            max={limits.sample}
            value={Number.isFinite(draft.sampleLimit) ? draft.sampleLimit : ""}
            disabled={disabled}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                sampleLimit: Number.parseInt(event.target.value, 10),
              }))
            }
          />
        </label>
      </div>

      <ol
        className={styles.questions}
        aria-label={`${pipeline.title}: questions`}
      >
        {draft.questions.map((item, index) => {
          const earlier = draft.questions
            .slice(0, index)
            .filter((other) => hasOptions(other.kind));
          const follow = Object.entries(item.when)[0];
          return (
            <li key={item.key} className={styles.question}>
              <div className={styles.questionHead}>
                <strong>
                  {index + 1}
                  {index === 0 ? (
                    <small> · measured in Analysis health</small>
                  ) : null}
                </strong>
                <code className={styles.key}>{item.key}</code>
                <span className={styles.tools}>
                  <button
                    type="button"
                    className={kitStyles.button}
                    data-variant="icon"
                    aria-label={`Move question ${index + 1} up`}
                    disabled={disabled || index === 0}
                    onClick={() => move(index, -1)}
                  >
                    <ArrowUp size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className={kitStyles.button}
                    data-variant="icon"
                    aria-label={`Move question ${index + 1} down`}
                    disabled={disabled || index === draft.questions.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    <ArrowDown size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className={kitStyles.button}
                    data-variant="icon"
                    aria-label={`Remove question ${index + 1}`}
                    disabled={disabled || draft.questions.length === 1}
                    onClick={() => remove(index)}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </span>
              </div>
              <label className={styles.field}>
                <span>Question</span>
                <input
                  value={item.label}
                  maxLength={limits.label}
                  placeholder="What should the reviewer answer?"
                  disabled={disabled}
                  onChange={(event) =>
                    update(index, { label: event.target.value })
                  }
                />
              </label>
              <div className={styles.row}>
                <label className={styles.field} data-narrow="">
                  <span>Kind</span>
                  <select
                    value={item.kind}
                    disabled={disabled}
                    onChange={(event) => {
                      const kind = event.target.value as QuestionKind;
                      update(index, {
                        kind,
                        options: hasOptions(kind)
                          ? optionsFromText(optionText[index] ?? "")
                          : [],
                      });
                    }}
                  >
                    {limits.kinds.map((kind) => (
                      <option key={kind} value={kind}>
                        {KIND_LABEL[kind]}
                      </option>
                    ))}
                  </select>
                </label>
                {hasOptions(item.kind) ? (
                  <label className={styles.field}>
                    <span>
                      Options, separated by commas
                      {index === 0 ? " (first = right, second = wrong)" : ""}
                    </span>
                    <input
                      value={optionText[index] ?? ""}
                      disabled={disabled}
                      placeholder="correct, wrong, unsure"
                      onChange={(event) => {
                        const text = event.target.value;
                        setOptionText((current) =>
                          current.map((value, at) =>
                            at === index ? text : value,
                          ),
                        );
                        update(index, { options: optionsFromText(text) });
                      }}
                    />
                  </label>
                ) : null}
                {index > 0 ? (
                  <label className={styles.field}>
                    <span>Ask</span>
                    <select
                      value={follow ? `${follow[0]}=${follow[1]}` : ""}
                      disabled={disabled}
                      onChange={(event) => {
                        const [after, option] = event.target.value.split("=");
                        update(index, {
                          when: after && option ? { [after]: option } : {},
                        });
                      }}
                    >
                      <option value="">Always</option>
                      {earlier.flatMap((other) =>
                        other.options.map((option) => (
                          <option
                            key={`${other.key}=${option}`}
                            value={`${other.key}=${option}`}
                          >
                            Only when “{other.label || other.key}” is {option}
                          </option>
                        )),
                      )}
                    </select>
                  </label>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      <div className={styles.actions}>
        <button
          type="button"
          className={kitStyles.button}
          disabled={disabled || draft.questions.length >= limits.questions}
          onClick={add}
        >
          <Plus size={14} aria-hidden="true" />
          Add question
        </button>
        <span className={styles.spacer} />
        {changed ? (
          <button
            type="button"
            className={kitStyles.button}
            data-variant="ghost"
            disabled={disabled}
            onClick={() => {
              setDraft(fromPipeline(pipeline));
              setOptionText(
                pipeline.questions.map((item) => item.options.join(", ")),
              );
              setMessage(null);
            }}
          >
            Undo changes
          </button>
        ) : null}
        <button
          type="button"
          className={kitStyles.button}
          data-variant="primary"
          disabled={disabled || !changed || problems.length > 0}
          onClick={save}
        >
          {state === "saving"
            ? "Saving…"
            : `Save as version ${pipeline.version + 1}`}
        </button>
      </div>
      {problems.length ? (
        <ul className={styles.problems} role="alert">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
      {message ? (
        <p
          className={
            message.tone === "bad" ? kitStyles.fieldError : styles.saved
          }
          role={message.tone === "bad" ? "alert" : "status"}
        >
          {message.text}
        </p>
      ) : null}
      {!canEdit ? (
        <p className={styles.readOnly}>
          Only the AC control accounts can change review pipelines.
        </p>
      ) : null}
    </div>
  );
}
