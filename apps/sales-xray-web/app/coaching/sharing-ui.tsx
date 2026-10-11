"use client";

import { Lock, Share2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, kitStyles, Panel, Skeleton } from "../ui/kit";
import {
  changeSharing,
  readSharing,
  sendContext,
  sendFeedback,
  type SharingView,
} from "./sharing-client";
import { REFLECTION } from "./coaching-copy";
import styles from "./coaching.module.css";

/** Private by default; one tap shares, one tap stops (owner decision 10 Oct). */
export function SharePanel({
  initial = null,
}: {
  /** A known state (design review); skips the read. */
  initial?: SharingView | null;
} = {}) {
  const [view, setView] = useState<SharingView | null>(initial);
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
    const result = await changeSharing(!view.shared, view.revision);
    setSaving(false);
    if (result.data) {
      setView(result.data);
      setError(null);
      setFailed(null);
    } else {
      setFailed(`${result.error} Your sharing is shown as it is now.`);
      setAttempt((value) => value + 1);
    }
  };
  const names = view?.reaches.map((reach) => reach.name).join(", ");
  return (
    <Panel
      title="Who sees your coaching"
      tools={
        view ? (
          <Badge tone={view.shared ? "accent" : "neutral"}>
            {view.shared ? "Shared" : "Private"}
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
            Personal workspace: only you can see this coaching.
          </p>
        ) : (
          <>
            <p>
              {view.shared
                ? `Your admins can see your focus, its likely reason and your mission${names ? `: ${names}` : ""}.`
                : `Only you can see it. Sharing lets your admins${names ? ` (${names})` : ""} see your focus, its likely reason and your mission.`}
            </p>
            <div className={styles.actions}>
              <Button
                variant={view.shared ? "secondary" : "primary"}
                onClick={() => void toggle()}
                disabled={saving}
              >
                {view.shared ? (
                  "Stop sharing"
                ) : (
                  <>
                    <Share2 size={14} aria-hidden="true" />
                    Share with your admins
                  </>
                )}
              </Button>
            </div>
            <p className={styles.note}>
              Your admins can already open your calls. Sharing also shows them
              this page. You can stop any time.
            </p>
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

/** The learner's own words about the focus (spec 12.2): kept, shown back. */
function AddContext({
  focusSkillId,
  originSubmissionId,
}: {
  focusSkillId: string;
  originSubmissionId: string;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
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
    const result = await sendContext({
      command_id: command,
      focus_skill_id: focusSkillId,
      mission_origin_submission_id: originSubmissionId,
      context: note,
    });
    setSaving(false);
    if (result.error) setError(result.error);
    else {
      setSaved(note);
      setText("");
      setOpen(false);
      setAttempted(null);
    }
  };
  if (!open)
    return (
      <>
        <Button onClick={() => setOpen(true)}>Add context</Button>
        {saved ? (
          <p role="status" className={styles.note}>
            Saved: “{saved}”. It shows with the likely reason.
          </p>
        ) : null}
      </>
    );
  return (
    <div className={styles.contextForm}>
      <label className={kitStyles.field}>
        <span className={kitStyles.fieldLabel}>
          What should we know about this focus?
        </span>
        <textarea
          value={text}
          maxLength={CONTEXT_LIMIT}
          rows={3}
          onChange={(event) => setText(event.target.value)}
        />
        <span className={kitStyles.fieldHint}>
          {text.length}/{CONTEXT_LIMIT} · Only you see it unless you share your
          coaching. It is deleted with your account.
        </span>
      </label>
      <div className={styles.actions}>
        <Button
          variant="primary"
          disabled={!note || saving}
          onClick={() => void save()}
        >
          Save
        </Button>
        <Button onClick={() => setOpen(false)} disabled={saving}>
          Cancel
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
    const result = await sendContext({
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
          (saving ? "Saving…" : chosen ? REFLECTION.saved : REFLECTION.hint)}
      </p>
    </div>
  );
}

export function FocusFeedback({
  focusSkillId,
  originSubmissionId,
  question,
}: {
  focusSkillId: string;
  originSubmissionId: string;
  /** The one reflection question, answered with a tap (spec pillar 6). */
  question?: string | null;
}) {
  const [state, setState] = useState<
    "idle" | "saving" | "agree" | "not_completely"
  >("idle");
  const [error, setError] = useState<string | null>(null);
  // One command per choice: retrying a choice repeats it; switching after a
  // failed try is a new answer, never a conflict with the first.
  const [commands] = useState(() => ({
    agree: crypto.randomUUID(),
    not_completely: crypto.randomUUID(),
  }));
  const send = async (agreement: "agree" | "not_completely") => {
    setState("saving");
    setError(null);
    const result = await sendFeedback({
      command_id: commands[agreement],
      agreement,
      focus_skill_id: focusSkillId,
      mission_origin_submission_id: originSubmissionId,
    });
    if (result.error) {
      setState("idle");
      setError(result.error);
    } else setState(agreement);
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
      <div className={styles.actions} role="group" aria-label="Your view">
        <Button
          onClick={() => void send("agree")}
          disabled={state !== "idle"}
          aria-pressed={state === "agree"}
        >
          Agree
        </Button>
        <Button
          onClick={() => void send("not_completely")}
          disabled={state !== "idle"}
          aria-pressed={state === "not_completely"}
        >
          Not completely
        </Button>
        <AddContext
          focusSkillId={focusSkillId}
          originSubmissionId={originSubmissionId}
        />
      </div>
      <p role="status" className={styles.note}>
        {done
          ? "Noted. Your mission stays the same."
          : (error ?? "Does this focus fit you? Tell us, or add context.")}
      </p>
    </>
  );
}
