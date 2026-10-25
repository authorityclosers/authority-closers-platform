"use client";

/**
 * Remind (owner, 24 Oct 2026; work-memory engine): a task on this lead in three
 * taps: what (Call back, WhatsApp, Email, Send file, Meeting, Other), when (in
 * an hour, this evening, tomorrow morning or a time picked), Save. A meeting
 * also asks where. It shows in Tasks on its day and the phone reminds once.
 */

import { useState } from "react";

import { notify } from "../notice-center";
import { Button } from "../ui/kit";
import { ActionSheet } from "./action-sheet";
import {
  LeadsError,
  addTask,
  commandId,
  firstName,
  type TaskKind,
  type TaskView,
} from "./leads-client";
import { TASK_KINDS, localInput, quickTimes } from "./task-words";
import styles from "./tasks.module.css";

export function RemindSheet({
  open,
  leadId,
  leadName,
  onClose,
  onSaved,
  now = () => new Date(),
}: {
  open: boolean;
  leadId: string;
  leadName: string;
  onClose: () => void;
  /** The task as saved; null when the phone kept it to send later. */
  onSaved: (task: TaskView | null) => void;
  now?: () => Date;
}) {
  const [kind, setKind] = useState<TaskKind>("call_back");
  const [quick, setQuick] = useState<string | null>("tomorrow");
  const [picked, setPicked] = useState("");
  const [where, setWhere] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One command per opening: a second tap on Save is the same task.
  const [command, setCommand] = useState(commandId);

  const times = quickTimes(now());
  const chosen = quick
    ? (times.find((time) => time.key === quick)?.at ?? null)
    : picked
      ? new Date(picked)
      : null;
  const valid = !!chosen && !Number.isNaN(chosen.getTime());

  const reset = () => {
    setKind("call_back");
    setQuick("tomorrow");
    setPicked("");
    setWhere("");
    setNote("");
    setError(null);
    setCommand(commandId());
  };

  const save = async () => {
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
      onClose={onClose}
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
          <div className={styles.times} role="group" aria-label="When">
            {times.map((time) => (
              <button
                key={time.key}
                type="button"
                className={styles.kind}
                aria-pressed={quick === time.key}
                onClick={() => setQuick(time.key)}
              >
                {time.label}
              </button>
            ))}
            <button
              type="button"
              className={styles.kind}
              aria-pressed={quick === null}
              onClick={() => {
                setQuick(null);
                if (!picked) setPicked(localInput(times[times.length - 1].at));
              }}
            >
              Pick a time
            </button>
          </div>
          {quick === null ? (
            <input
              className={styles.input}
              type="datetime-local"
              aria-label="Date and time"
              value={picked}
              min={localInput(now())}
              onChange={(event) => setPicked(event.target.value)}
            />
          ) : null}
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
          <Button variant="ghost" onClick={onClose}>
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
