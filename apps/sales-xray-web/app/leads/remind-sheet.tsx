"use client";

/**
 * Remind (owner, 24 Oct 2026; work-memory engine): a task on this lead in three
 * taps: what (Call back, WhatsApp, Email, Send file, Meeting, Other), when (in
 * 1, 2, 5, 15 or 30 min, in 1 hour, tomorrow morning, or any date and time:
 * the shared reminder picker, owner 22 Nov 2026), Save. A meeting also asks
 * where. It shows in Tasks on its day and the phone reminds once, at the time
 * shown.
 */

import { useEffect, useState } from "react";

import { notify } from "../notice-center";
import { closingByBack } from "../ui/back-close";
import { Button } from "../ui/kit";
import { ActionSheet } from "./action-sheet";
import { keepDraft, readDraft } from "./drafts";
import {
  LeadsError,
  addTask,
  commandId,
  firstName,
  type TaskKind,
  type TaskView,
} from "./leads-client";
import { ReminderTime, reminderAt, type ReminderPick } from "./reminder-time";
import { isReminderPreset, type OpeningHours } from "./reminder-times";
import { TASK_KINDS } from "./task-words";
import styles from "./tasks.module.css";

/**
 * What was written for a reminder, kept on this device for the lead
 * (drafts.ts): a refresh loses nothing, and the sheet opened again shows it
 * (the robot, 9 Nov 2026: 40 characters in "Follow-up" gone after a refresh at
 * 360). Saving, Cancel, X, a tap outside or a swipe down drops it; Back keeps
 * it.
 */
type Kept = {
  kind: TaskKind;
  quick: string | null;
  picked: string;
  where: string;
  note: string;
};

const keptKey = (leadId: string) => `remind:${leadId}`;

function keptRemind(leadId: string): Kept | null {
  try {
    const kept = JSON.parse(
      readDraft(keptKey(leadId)) || "null",
    ) as Partial<Kept> | null;
    if (!kept || typeof kept !== "object") return null;
    const known = TASK_KINDS.some((item) => item.key === kept.kind);
    return {
      kind: known ? (kept.kind as TaskKind) : "call_back",
      // An older build kept "tomorrow" or "afternoon": tomorrow morning now.
      quick:
        typeof kept.quick === "string"
          ? isReminderPreset(kept.quick)
            ? kept.quick
            : "morning"
          : null,
      picked: typeof kept.picked === "string" ? kept.picked : "",
      where: typeof kept.where === "string" ? kept.where : "",
      note: typeof kept.note === "string" ? kept.note : "",
    };
  } catch {
    return null;
  }
}

export function RemindSheet({
  open,
  leadId,
  leadName,
  onClose,
  onSaved,
  hours = null,
  now = () => new Date(),
}: {
  open: boolean;
  leadId: string;
  leadName: string;
  onClose: () => void;
  /** The task as saved; null when the phone kept it to send later. */
  onSaved: (task: TaskView | null) => void;
  /** The team's hours (the lead's ``work_hours``): Tomorrow morning is their opening. */
  hours?: OpeningHours;
  now?: () => Date;
}) {
  const [kind, setKind] = useState<TaskKind>("call_back");
  // A preset, or null for a picked date and time (kept drafts say it so).
  const [quick, setQuick] = useState<string | null>("morning");
  const [picked, setPicked] = useState("");
  const [where, setWhere] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One command per opening: a second tap on Save is the same task.
  const [command, setCommand] = useState(commandId);
  // Opened with nothing written yet: what was kept comes back.
  const [openedFor, setOpenedFor] = useState(false);
  if (openedFor !== open) {
    setOpenedFor(open);
    const kept = open && !note && !where ? keptRemind(leadId) : null;
    if (kept && (kept.note.trim() || kept.where.trim())) {
      setKind(kept.kind);
      setQuick(kept.quick);
      setPicked(kept.picked);
      setWhere(kept.where);
      setNote(kept.note);
    }
  }
  // Kept as it is written; nothing written, nothing kept.
  useEffect(() => {
    if (!open) return;
    keepDraft(
      keptKey(leadId),
      note.trim() || where.trim()
        ? JSON.stringify({ kind, quick, picked, where, note } satisfies Kept)
        : "",
    );
  }, [open, leadId, kind, quick, picked, where, note]);

  const pick: ReminderPick | null =
    quick === null ? "custom" : isReminderPreset(quick) ? quick : null;
  const chosenAt = (at: Date) => reminderAt(pick, picked, at, hours);
  const chosen = chosenAt(now());
  // A time already gone is not a reminder (the picker says so).
  const valid = !!chosen && chosen.getTime() >= now().getTime() - 30_000;

  const reset = () => {
    setKind("call_back");
    setQuick("morning");
    setPicked("");
    setWhere("");
    setNote("");
    setError(null);
    setCommand(commandId());
    keepDraft(keptKey(leadId), "");
  };
  // Back keeps what was written for next time; Cancel, X, a tap outside or a
  // swipe down drops it.
  const close = () => {
    if (!closingByBack()) reset();
    onClose();
  };

  const save = async () => {
    // Counted now: "In 2 min" is two minutes from the tap on Save.
    const chosen = chosenAt(now());
    if (!valid || !chosen) {
      setError("Pick when.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const task = await addTask(
        leadId,
        {
          kind,
          starts_at: chosen.toISOString(),
          ends_at:
            kind === "meeting"
              ? new Date(chosen.getTime() + 60 * 60_000).toISOString()
              : null,
          location: kind === "meeting" ? where.trim() : null,
          note: note.trim(),
        },
        command,
      );
      reset();
      onSaved(task);
    } catch (reason) {
      if (reason instanceof LeadsError && reason.kept) {
        notify({
          id: `remind-kept-${leadId}`,
          tone: "info",
          title: "Reminder saved on this phone",
          message: reason.message,
        });
        reset();
        onSaved(null);
        return;
      }
      setError(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <ActionSheet
      open={open}
      title="Remind me"
      sub={`About ${firstName(leadName)}`}
      onClose={close}
    >
      <div className={styles.remind}>
        <div>
          <h3>What</h3>
          <div className={styles.kinds} role="group" aria-label="What to do">
            {TASK_KINDS.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.key}
                  type="button"
                  className={styles.kind}
                  aria-pressed={kind === item.key}
                  onClick={() => setKind(item.key)}
                >
                  <Icon size={16} aria-hidden="true" />
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <h3>When</h3>
          <ReminderTime
            pick={pick}
            custom={picked}
            hours={hours}
            now={now}
            onPick={(next) => setQuick(next === "custom" ? null : next)}
            onCustom={setPicked}
          />
        </div>
        {kind === "meeting" ? (
          <label className={styles.field}>
            <span>Where</span>
            <input
              className={styles.input}
              value={where}
              maxLength={300}
              placeholder="Office, site or a video link"
              onChange={(event) => setWhere(event.target.value)}
            />
          </label>
        ) : null}
        <label className={styles.field}>
          <span>Note</span>
          <textarea
            className={styles.input}
            value={note}
            maxLength={1000}
            placeholder="What you promised, in a few words"
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        <div className={styles.save}>
          <Button variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void save()}
            disabled={saving || !valid}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </ActionSheet>
  );
}
