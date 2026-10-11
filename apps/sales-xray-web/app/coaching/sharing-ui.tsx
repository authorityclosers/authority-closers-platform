"use client";

import { Lock, Share2 } from "lucide-react";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { Badge, Button, kitStyles, Panel, Skeleton } from "../ui/kit";
import {
  changeSharing,
  readSharing,
  sendContext,
  sendFeedback,
  type SharingView,
} from "./sharing-client";
import type { Evidence } from "./coaching-client";
import { DISAGREE, FEEDBACK, REFLECTION, SHARING } from "./coaching-copy";
import { timeLabel } from "./coaching-format";
import styles from "./coaching.module.css";

/** Where Coaching's own-account writes go. */
export type CoachingWriter = {
  sharing: typeof changeSharing;
  context: typeof sendContext;
  feedback: typeof sendFeedback;
};

/**
 * The API by default. The no-login design review provides an in-page writer,
 * so its taps show the real flow without sending anything.
 */
export const CoachingWrites = createContext<CoachingWriter>({
  sharing: changeSharing,
  context: sendContext,
  feedback: sendFeedback,
});

/** Private by default; one tap shares, one tap stops (owner decision 10 Oct). */
export function SharePanel({
  initial = null,
}: {
  /** A known state (design review); skips the read. */
  initial?: SharingView | null;
} = {}) {
  const [view, setView] = useState<SharingView | null>(initial);
  const writes = useContext(CoachingWrites);
  const [error, setError] = useState<string | null>(null);
  // A failed tap's message, kept through the reload that follows it.
  const [failed, setFailed] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (initial && attempt === 0) return;
    const controller = new AbortController();
    void readSharing(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setView(result.data);
      setError(result.error);
    });
    return () => controller.abort();
  }, [attempt, initial]);
  const toggle = async () => {
    if (!view) return;
    setSaving(true);
    const result = await writes.sharing(!view.shared, view.revision);
    setSaving(false);
    if (result.data) {
      setView(result.data);
      setError(null);
      setFailed(null);
    } else {
      setFailed(`${result.error} ${SHARING.unchanged}`);
      setAttempt((value) => value + 1);
    }
  };
  const names = view?.reaches.map((reach) => reach.name).join(", ");
  return (
    <Panel
      title={SHARING.title}
      tools={
        view ? (
          <Badge tone={view.shared ? "accent" : "neutral"}>
            {view.shared ? SHARING.shared : SHARING.private}
          </Badge>
        ) : null
      }
    >
      <div className={styles.body}>
        {!view && !error ? (
          <>
            <Skeleton height={13} />
            <Skeleton width="60%" height={13} />
          </>
        ) : !view ? (
          <p className={styles.status}>{error}</p>
        ) : !view.available ? (
          <p className={styles.eyebrow}>
            <Lock size={14} aria-hidden="true" />
            {SHARING.personal}
          </p>
        ) : (
          <>
            <p>
              {view.shared
                ? SHARING.sharedText(names)
                : SHARING.privateText(names)}
            </p>
            <div className={styles.actions}>
              <Button
                variant={view.shared ? "secondary" : "primary"}
                onClick={() => void toggle()}
                disabled={saving}
              >
                {view.shared ? (
                  SHARING.stop
                ) : (
                  <>
                    <Share2 size={14} aria-hidden="true" />
                    {SHARING.share}
                  </>
                )}
              </Button>
            </div>
            <p className={styles.note}>{SHARING.note}</p>
            {failed || error ? (
              <p role="status" className={styles.status}>
                {failed ?? error}
              </p>
            ) : null}
          </>
        )}
      </div>
    </Panel>
  );
}

/** Agree / not completely with the current focus; never changes a score. */
const CONTEXT_LIMIT = 1000;

/**
 * What the focus rests on (spec pillar 6, disagreement step 2): each moment's
 * call, time and what the report saw, shown before asking what we missed.
 */
function FocusBasis({ evidence }: { evidence: readonly Evidence[] }) {
  if (!evidence.length) return null;
  return (
    <div className={styles.basis}>
      <p className={styles.basisHead}>
        {DISAGREE.basis}
        <a href="#coaching-why">{DISAGREE.replay}</a>
      </p>
      <ul aria-label={DISAGREE.basis}>
        {evidence.map((moment) => (
          <li
            key={`${moment.submission_id}:${moment.segment_id}:${moment.start_ms}`}
          >
            <span>
              {moment.call_label} · {timeLabel(moment.start_ms)}
            </span>
            {moment.observation}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The learner's own words about the focus (spec 12.2): kept, shown back.
 * It stays mounted while closed, so a retry after a failed save repeats the
 * same command.
 */
function ContextForm({
  focusSkillId,
  originSubmissionId,
  open,
  missed,
  evidence,
  onSaved,
  onCancel,
}: {
  focusSkillId: string;
  originSubmissionId: string;
  open: boolean;
  /** Opened by "Not completely": ask what we missed. */
  missed: boolean;
  evidence: readonly Evidence[];
  onSaved: (note: string) => void;
  onCancel: () => void;
}) {
  const writes = useContext(CoachingWrites);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One command per text: a retry of the same note is the same request,
  // an edited note is a new one (never a conflict with the first try).
  const [attempted, setAttempted] = useState<{
    text: string;
    command: string;
  } | null>(null);
  const note = text.trim();
  const save = async () => {
    setSaving(true);
    setError(null);
    const command =
      attempted?.text === note ? attempted.command : crypto.randomUUID();
    setAttempted({ text: note, command });
    const result = await writes.context({
      command_id: command,
      focus_skill_id: focusSkillId,
      mission_origin_submission_id: originSubmissionId,
      context: note,
    });
    setSaving(false);
    if (result.error) setError(result.error);
    else {
      setText("");
      setAttempted(null);
      onSaved(note);
    }
  };
  if (!open) return null;
  return (
    <div className={styles.contextForm}>
      <FocusBasis evidence={evidence} />
      <label className={kitStyles.field}>
        <span className={kitStyles.fieldLabel}>
          {missed ? DISAGREE.missed : DISAGREE.context}
        </span>
        <textarea
          value={text}
          maxLength={CONTEXT_LIMIT}
          rows={3}
          onChange={(event) => setText(event.target.value)}
        />
        <span className={kitStyles.fieldHint}>
          {text.length}/{CONTEXT_LIMIT} · {FEEDBACK.contextHint}
        </span>
      </label>
      <div className={styles.actions}>
        <Button
          variant="primary"
          disabled={!note || saving}
          onClick={() => void save()}
        >
          {FEEDBACK.save}
        </Button>
        <Button onClick={onCancel} disabled={saving}>
          {FEEDBACK.cancel}
        </Button>
      </div>
      {error ? (
        <p role="status" className={styles.status}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * One reflection question with Dipak's possible answers (spec pillar 6). A
 * tap keeps that answer as the learner's context; the newest one shows with
 * the likely reason. A retry after a failure repeats the same command.
 */
function Reflection({
  question,
  focusSkillId,
  originSubmissionId,
}: {
  question: string;
  focusSkillId: string;
  originSubmissionId: string;
}) {
  const writes = useContext(CoachingWrites);
  const [chosen, setChosen] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const failed = useRef<{ answer: string; command: string } | null>(null);
  const pick = async (answer: string) => {
    const command =
      failed.current?.answer === answer
        ? failed.current.command
        : crypto.randomUUID();
    setSaving(answer);
    setError(null);
    const result = await writes.context({
      command_id: command,
      focus_skill_id: focusSkillId,
      mission_origin_submission_id: originSubmissionId,
      context: answer,
    });
    setSaving(null);
    if (result.error) {
      failed.current = { answer, command };
      setError(result.error);
    } else {
      failed.current = null;
      setChosen(answer);
    }
  };
  return (
    <div className={styles.reflection}>
      <p className={styles.reflectionQuestion}>{question}</p>
      <div className={styles.answers} role="group" aria-label={question}>
        {REFLECTION.answers.map((answer) => (
          <button
            key={answer}
            type="button"
            className={styles.answer}
            aria-pressed={chosen === answer}
            disabled={saving !== null}
            onClick={() => void pick(answer)}
          >
            {answer}
          </button>
        ))}
      </div>
      <p role="status" className={styles.note}>
        {error ??
          (saving
            ? FEEDBACK.saving
            : chosen
              ? REFLECTION.saved
              : REFLECTION.hint)}
      </p>
    </div>
  );
}

export function FocusFeedback({
  focusSkillId,
  originSubmissionId,
  question,
  evidence = [],
}: {
  focusSkillId: string;
  originSubmissionId: string;
  /** The one reflection question, answered with a tap (spec pillar 6). */
  question?: string | null;
  /** The moments behind the focus, shown before asking what we missed. */
  evidence?: readonly Evidence[];
}) {
  const writes = useContext(CoachingWrites);
  const [state, setState] = useState<
    "idle" | "saving" | "agree" | "not_completely"
  >("idle");
  const [error, setError] = useState<string | null>(null);
  const [contextOpen, setContextOpen] = useState(false);
  const [missed, setMissed] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  // One command per choice: retrying a choice repeats it; switching after a
  // failed try is a new answer, never a conflict with the first.
  const [commands] = useState(() => ({
    agree: crypto.randomUUID(),
    not_completely: crypto.randomUUID(),
  }));
  const send = async (agreement: "agree" | "not_completely") => {
    setState("saving");
    setError(null);
    const result = await writes.feedback({
      command_id: commands[agreement],
      agreement,
      focus_skill_id: focusSkillId,
      mission_origin_submission_id: originSubmissionId,
    });
    if (result.error) {
      setState("idle");
      setError(result.error);
      return;
    }
    setState(agreement);
    // Spec pillar 6 disagreement flow: show the evidence, ask what we missed.
    if (agreement === "not_completely") {
      setMissed(true);
      setContextOpen(true);
    }
  };
  const done = state === "agree" || state === "not_completely";
  return (
    <>
      {question ? (
        <Reflection
          question={question}
          focusSkillId={focusSkillId}
          originSubmissionId={originSubmissionId}
        />
      ) : null}
      <div className={styles.actions} role="group" aria-label={FEEDBACK.group}>
        <Button
          onClick={() => void send("agree")}
          disabled={state !== "idle"}
          aria-pressed={state === "agree"}
        >
          {FEEDBACK.agree}
        </Button>
        <Button
          onClick={() => void send("not_completely")}
          disabled={state !== "idle"}
          aria-pressed={state === "not_completely"}
        >
          {FEEDBACK.notCompletely}
        </Button>
        {contextOpen ? null : (
          <Button
            onClick={() => {
              setMissed(false);
              setContextOpen(true);
            }}
          >
            {FEEDBACK.addContext}
          </Button>
        )}
      </div>
      <p role="status" className={styles.note}>
        {state === "not_completely" && contextOpen
          ? DISAGREE.noted
          : done
            ? FEEDBACK.noted
            : (error ?? FEEDBACK.ask)}
      </p>
      <ContextForm
        focusSkillId={focusSkillId}
        originSubmissionId={originSubmissionId}
        open={contextOpen}
        missed={missed}
        evidence={evidence}
        onSaved={(note) => {
          setSaved(note);
          setContextOpen(false);
        }}
        onCancel={() => setContextOpen(false)}
      />
      {saved && !contextOpen ? (
        <p role="status" className={styles.note}>
          Saved: “{saved}”. It shows with the likely reason.
        </p>
      ) : null}
    </>
  );
}
