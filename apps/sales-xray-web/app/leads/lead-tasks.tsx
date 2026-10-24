"use client";

/**
 * The lead's open tasks on the lead, the next one first (work-memory engine):
 * what, when, and Done. Everything else about a task is in Tasks.
 */

import { Check } from "lucide-react";
import { useState } from "react";

import { notify } from "../notice-center";
import {
  LeadsError,
  readLead,
  taskAction,
  type LeadDetail,
  type TaskView,
} from "./leads-client";
import { dueWords, kindOf } from "./task-words";
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
  const tasks = detail.tasks ?? [];
  if (tasks.length === 0) return null;

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
    </section>
  );
}
