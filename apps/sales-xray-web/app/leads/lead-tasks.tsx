"use client";

/**
 * The lead's open tasks on the lead, the next one first (work-memory engine):
 * what, when, Snooze and Done (competitor teardown 10, 2 Nov 2026: Snooze
 * beside Done, as in Tasks). Everything else about a task is in Tasks.
 */

import { Check, Clock } from "lucide-react";
import { useState } from "react";

import { notify } from "../notice-center";
import { ActionSheet } from "./action-sheet";
import {
  LeadsError,
  readLead,
  snoozeTask,
  taskAction,
  type LeadDetail,
  type TaskSnoozeChoice,
  type TaskView,
} from "./leads-client";
import { dueWords, kindOf, SNOOZES } from "./task-words";
import styles from "./tasks.module.css";

export function LeadTasks({
  detail,
  onChanged,
  now = () => new Date(),
}: {
  detail: LeadDetail;
  onChanged: (detail: LeadDetail) => void;
  now?: () => Date;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [later, setLater] = useState<TaskView | null>(null);
  const tasks = detail.tasks ?? [];
  if (tasks.length === 0) return null;

  // Snooze, with the Tasks list's choices ("This evening" only before 5 PM).
  const snooze = async (task: TaskView, choice: TaskSnoozeChoice) => {
    setLater(null);
    setBusy(task.task_id);
    try {
      const after = await snoozeTask(task, choice);
      notify({
        id: `lead-task-${task.task_id}`,
        tone: "success",
        title: `Moved to ${dueWords(after, now())}`,
        message: task.title,
        timeout: 4000,
      });
      onChanged(await readLead(detail.lead.lead_id));
    } catch (reason) {
      const kept = reason instanceof LeadsError && reason.kept;
      notify({
        id: `lead-task-${task.task_id}`,
        tone: kept ? "info" : "error",
        title: kept ? "Moved" : "Not moved",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    } finally {
      setBusy(null);
    }
  };
  const snoozes = SNOOZES.filter(
    (choice) => choice.key !== "evening" || now().getHours() < 17,
  );

  const done = async (task: TaskView) => {
    setBusy(task.task_id);
    try {
      await taskAction(task, "done");
      onChanged(await readLead(detail.lead.lead_id));
    } catch (reason) {
      const kept = reason instanceof LeadsError && reason.kept;
      notify({
        id: `lead-task-${task.task_id}`,
        tone: kept ? "info" : "error",
        title: kept ? `Done: ${task.title}` : "Not marked done",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className={styles.leadTasks} aria-label="Open tasks">
      <h3>
        {tasks.length === 1 ? "Open task" : `Open tasks (${tasks.length})`}
      </h3>
      <ol className={styles.list}>
        {tasks.slice(0, 3).map((task) => {
          const kind = kindOf(task.kind);
          const Icon = kind.icon;
          return (
            <li key={task.task_id} className={styles.item}>
              <span className={styles.row} data-static="">
                <span
                  className={styles.icon}
                  data-kind={task.kind}
                  aria-hidden="true"
                >
                  <Icon size={16} />
                </span>
                <span className={styles.text}>
                  <strong>{kind.label}</strong>
                  {task.note ? <small>{task.note}</small> : null}
                </span>
                <time
                  dateTime={task.starts_at}
                  data-late={task.overdue ? "" : undefined}
                >
                  {dueWords(task, now())}
                </time>
              </span>
              {detail.can_edit ? (
                <span className={styles.acts}>
                  <button
                    type="button"
                    className={styles.act}
                    aria-label={`Later: ${task.title}`}
                    disabled={busy === task.task_id}
                    onClick={() => setLater(task)}
                  >
                    <Clock size={18} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className={styles.act}
                    data-done=""
                    aria-label={`Done: ${task.title}`}
                    disabled={busy === task.task_id}
                    onClick={() => void done(task)}
                  >
                    <Check size={18} aria-hidden="true" />
                  </button>
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      <ActionSheet
        open={!!later}
        title="Do it later"
        sub={later?.title}
        onClose={() => setLater(null)}
      >
        <div className={styles.choices}>
          {snoozes.map((choice) => (
            <button
              key={choice.key}
              type="button"
              className={styles.choice}
              onClick={() => later && void snooze(later, choice.key)}
            >
              {choice.label}
            </button>
          ))}
        </div>
      </ActionSheet>
    </section>
  );
}
