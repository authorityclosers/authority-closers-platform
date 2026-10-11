"use client";

import { Lock, Share2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Panel, Skeleton } from "../ui/kit";
import {
  changeSharing,
  readSharing,
  sendFeedback,
  type SharingView,
} from "./sharing-client";
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
    } else {
      setError(result.error);
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
              Sharing adds your Coaching view to what your admins can already
              open in your calls. You can stop sharing at any time.
            </p>
            {error ? (
              <p role="status" className={styles.status}>
                {error}
              </p>
            ) : null}
          </>
        )}
      </div>
    </Panel>
  );
}

/** Agree / not completely with the current focus; never changes a score. */
export function FocusFeedback({
  focusSkillId,
  originSubmissionId,
}: {
  focusSkillId: string;
  originSubmissionId: string;
}) {
  const [state, setState] = useState<
    "idle" | "saving" | "agree" | "not_completely"
  >("idle");
  const [error, setError] = useState<string | null>(null);
  const [command] = useState(() => crypto.randomUUID());
  const send = async (agreement: "agree" | "not_completely") => {
    setState("saving");
    setError(null);
    const result = await sendFeedback({
      command_id: command,
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
        <Button disabled title="Coming soon">
          Add context
        </Button>
      </div>
      <p role="status" className={styles.note}>
        {done
          ? "Recorded. It does not change your mission or any score."
          : (error ??
            "Tell us whether this focus fits. Adding written context comes next.")}
      </p>
    </>
  );
}
