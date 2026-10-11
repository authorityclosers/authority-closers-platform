"use client";

/**
 * The reviewer's side of one call: a verdict on each pillar, skill and the
 * coaching (↑/↓ choose a section, 1/2/3 = correct/partly/wrong), notes,
 * Dipak's gold label, training/test marks and the review state. Every change
 * is a new, audited label (append-only); the page re-reads from the server.
 * Internal only: never an official score and never shown to reps.
 */
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { command, newKey } from "../lib/client-api";
import { Badge, Field, kitStyles } from "../ui/kit";
import { when } from "./call-data";
import {
  GAP_TYPES,
  REVIEW_LABEL,
  REVIEW_TONE,
  SKILL_STATES,
  VERDICTS,
  VERDICT_SECTIONS,
  latest,
  myVerdicts,
  sectionLabel,
  type Labels,
  type Verdict,
} from "./labels-data";
import { REPORT_SKILLS } from "./report-pillars";
import { typing } from "./queue-keys";
import styles from "./review.module.css";

type Send = (body: Record<string, unknown>) => Promise<boolean>;

export function ReviewPanel({
  recordingId,
  runId,
  labels,
}: {
  recordingId: string;
  runId: string;
  labels: Labels;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{
    tone: "good" | "bad";
    text: string;
  } | null>(null);
  const [active, setActive] = useState(0);
  const [pending, setPending] = useState<Record<string, Verdict>>({});
  const verdicts = { ...myVerdicts(labels, runId, null), ...pending };

  const send: Send = async (body) => {
    const id = String(body.section ?? body.kind);
    setBusy(id);
    setMessage(null);
    const result = await command(
      `/v1/admin/conversation/calls/${recordingId}/labels`,
      body,
      newKey(),
    );
    setBusy(null);
    if (!result.ok) {
      setMessage({ tone: "bad", text: result.message });
      return false;
    }
    setMessage({ tone: "good", text: "Saved." });
    router.refresh();
    return true;
  };
  const judge = async (section: string, verdict: Verdict) => {
    setPending((value) => ({ ...value, [section]: verdict }));
    const ok = await send({
      kind: "verdict",
      run_id: runId,
      section,
      value: { verdict },
    });
    if (!ok)
      setPending((value) => {
        const next = { ...value };
        delete next[section];
        return next;
      });
  };

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        typing(event.target)
      )
        return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setActive((value) =>
          Math.max(
            0,
            Math.min(
              VERDICT_SECTIONS.length - 1,
              value + (event.key === "ArrowDown" ? 1 : -1),
            ),
          ),
        );
        return;
      }
      const verdict = VERDICTS.find((item) => item.key === event.key);
      const section = VERDICT_SECTIONS[active];
      if (verdict && section) {
        event.preventDefault();
        void judge(section.id, verdict.value);
        setActive((value) => Math.min(VERDICT_SECTIONS.length - 1, value + 1));
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  });

  const status = latest(labels, "status");
  const dataUse = latest(labels, "data_use");
  return (
    <div className={styles.reading}>
      <div className={styles.reviewHead}>
        <span>
          Review state{" "}
          <Badge tone={REVIEW_TONE[labels.state]}>
            {REVIEW_LABEL[labels.state]}
          </Badge>
        </span>
        <span className={styles.reviewActions}>
          {status?.value.state === "done" ? (
            <button
              type="button"
              className={kitStyles.button}
              disabled={!!busy}
              onClick={() =>
                void send({ kind: "status", value: { state: "needs_review" } })
              }
            >
              Reopen
            </button>
          ) : (
            <button
              type="button"
              className={kitStyles.button}
              data-variant="primary"
              disabled={!!busy}
              onClick={() =>
                void send({ kind: "status", value: { state: "done" } })
              }
            >
              Mark review done
            </button>
          )}
        </span>
      </div>
      {message ? (
        <p
          role={message.tone === "bad" ? "alert" : "status"}
          className={
            message.tone === "bad" ? kitStyles.fieldError : kitStyles.fieldHint
          }
        >
          {message.text}
        </p>
      ) : null}

      <section className={styles.block} aria-label="Verdicts">
        <h3 className={styles.blockTitle}>
          Verdicts <small>↑ ↓ choose · 1 correct · 2 partly · 3 wrong</small>
        </h3>
        <ul className={styles.verdicts}>
          {VERDICT_SECTIONS.map((section, index) => (
            <li
              key={section.id}
              data-active={index === active ? "" : undefined}
              onClick={() => setActive(index)}
            >
              <span className={styles.verdictLabel}>
                {section.label}
                <small>{section.group}</small>
              </span>
              <span
                className={styles.verdictButtons}
                role="group"
                aria-label={`Verdict on ${section.label}`}
              >
                {VERDICTS.map((verdict) => (
                  <button
                    key={verdict.value}
                    type="button"
                    data-verdict={verdict.value}
                    aria-pressed={verdicts[section.id] === verdict.value}
                    disabled={busy === section.id}
                    onClick={() => void judge(section.id, verdict.value)}
                  >
                    {verdict.label}
                  </button>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <NoteForm send={send} busy={busy === "note"} />
      <GoldForm
        send={send}
        runId={runId}
        current={latest(labels, "gold")?.value ?? null}
        busy={busy === "gold"}
      />

      <section className={styles.block} aria-label="Data use">
        <h3 className={styles.blockTitle}>
          Use this call as{" "}
          <small>for prompt work; never mixed into real teams</small>
        </h3>
        <span
          className={styles.verdictButtons}
          role="group"
          aria-label="Data use"
        >
          {(["training", "test", "none"] as const).map((use) => (
            <button
              key={use}
              type="button"
              aria-pressed={(dataUse?.value.use ?? "none") === use}
              disabled={busy === "data_use"}
              onClick={() => void send({ kind: "data_use", value: { use } })}
            >
              {use === "none"
                ? "Neither"
                : use === "training"
                  ? "Training data"
                  : "Test data"}
            </button>
          ))}
        </span>
      </section>

      <section className={styles.block} aria-label="History">
        <h3 className={styles.blockTitle}>
          History <small>{labels.history.length} labels, oldest first</small>
        </h3>
        {labels.history.length ? (
          <ul className={styles.history}>
            {labels.history.map((row) => (
              <li
                key={row.id}
                data-superseded={
                  labels.effective.some((item) => item.id === row.id)
                    ? undefined
                    : ""
                }
              >
                <span>{when(row.createdAt)}</span>
                <span>
                  {row.kind === "verdict"
                    ? `${sectionLabel(row.section ?? "")}: ${String(row.value.verdict)}`
                    : row.kind === "note"
                      ? `Note: ${String(row.value.text)}`
                      : row.kind === "gold"
                        ? "Gold label saved"
                        : row.kind === "data_use"
                          ? `Marked as ${String(row.value.use)}`
                          : `Review ${String(row.value.state).replace("_", " ")}`}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.gap}>
            No labels yet. Start with the verdicts above.
          </p>
        )}
      </section>
    </div>
  );
}

function NoteForm({ send, busy }: { send: Send; busy: boolean }) {
  const [text, setText] = useState("");
  const submit = async () => {
    if (!text.trim() || busy) return;
    if (await send({ kind: "note", value: { text: text.trim() } })) setText("");
  };
  return (
    <section className={styles.block} aria-label="Notes">
      <h3 className={styles.blockTitle}>
        Note <small>Ctrl+Enter adds it</small>
      </h3>
      <div className={styles.noteForm}>
        <textarea
          aria-label="Note about this call"
          value={text}
          maxLength={4000}
          placeholder="What's right or wrong, and why"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <button
          type="button"
          className={kitStyles.button}
          disabled={!text.trim() || busy}
          onClick={() => void submit()}
        >
          {busy ? "Adding…" : "Add note"}
        </button>
      </div>
    </section>
  );
}

function GoldForm({
  send,
  runId,
  current,
  busy,
}: {
  send: Send;
  runId: string;
  current: Record<string, unknown> | null;
  busy: boolean;
}) {
  const initial = useMemo(
    () => ({
      focus: typeof current?.focus === "string" ? current.focus : "",
      rootCause:
        typeof current?.root_cause === "string" ? current.root_cause : "",
      rootCauseNote:
        typeof current?.root_cause_note === "string"
          ? current.root_cause_note
          : "",
      coaching: typeof current?.coaching === "string" ? current.coaching : "",
      states:
        current &&
        typeof current.skill_states === "object" &&
        current.skill_states
          ? (current.skill_states as Record<string, string>)
          : {},
    }),
    [current],
  );
  const [form, setForm] = useState(initial);
  // A newly saved gold label (after the page re-reads) resets the form to it.
  const [shown, setShown] = useState(initial);
  if (shown !== initial) {
    setShown(initial);
    setForm(initial);
  }
  const changed = JSON.stringify(form) !== JSON.stringify(initial);
  return (
    <section className={styles.block} aria-label="Gold label">
      <h3 className={styles.blockTitle}>
        Gold label <small>what the right report would say</small>
      </h3>
      <div className={styles.goldGrid}>
        <Field label="Right focus">
          <select
            value={form.focus}
            onChange={(event) =>
              setForm({ ...form, focus: event.target.value })
            }
          >
            <option value="">Not set</option>
            {REPORT_SKILLS.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Root cause (a hypothesis)">
          <select
            value={form.rootCause}
            onChange={(event) =>
              setForm({ ...form, rootCause: event.target.value })
            }
          >
            <option value="">Not set</option>
            {GAP_TYPES.map((gap) => (
              <option key={gap.value} value={gap.value}>
                {gap.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Why you think so" wide>
          <textarea
            value={form.rootCauseNote}
            maxLength={1000}
            onChange={(event) =>
              setForm({ ...form, rootCauseNote: event.target.value })
            }
          />
        </Field>
        <Field label="The right coaching" wide>
          <textarea
            value={form.coaching}
            maxLength={2000}
            onChange={(event) =>
              setForm({ ...form, coaching: event.target.value })
            }
          />
        </Field>
      </div>
      <table className={styles.metrics} aria-label="Gold skill states">
        <thead>
          <tr>
            <th scope="col">Skill</th>
            <th scope="col">Right state</th>
          </tr>
        </thead>
        <tbody>
          {REPORT_SKILLS.map(([id, label]) => (
            <tr key={id}>
              <th scope="row">{label}</th>
              <td>
                <select
                  aria-label={`Right state for ${label}`}
                  value={form.states[id] ?? ""}
                  onChange={(event) => {
                    const states = { ...form.states };
                    if (event.target.value) states[id] = event.target.value;
                    else delete states[id];
                    setForm({ ...form, states });
                  }}
                >
                  <option value="">Not set</option>
                  {SKILL_STATES.map((state) => (
                    <option key={state.value} value={state.value}>
                      {state.label}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        className={kitStyles.button}
        data-variant="primary"
        disabled={!changed || busy}
        onClick={() =>
          void send({
            kind: "gold",
            run_id: runId,
            value: {
              focus: form.focus || null,
              root_cause: form.rootCause || null,
              root_cause_note: form.rootCauseNote.trim() || null,
              coaching: form.coaching.trim() || null,
              skill_states: form.states,
            },
          })
        }
      >
        {busy
          ? "Saving…"
          : current
            ? "Save a new gold label"
            : "Save gold label"}
      </button>
    </section>
  );
}
