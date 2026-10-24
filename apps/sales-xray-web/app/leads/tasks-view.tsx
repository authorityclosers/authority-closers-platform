"use client";

/**
 * Tasks (owner, 24 Oct 2026; work-memory engine): the seller's own promises, in
 * three lists: Overdue, Today and Upcoming, earliest first. Done takes a task
 * off with an Undo; Later moves it by 15 minutes, an hour, to this evening or
 * tomorrow. A tap anywhere else opens the lead.
 */

import { Check, Clock, ListTodo, MapPin } from "lucide-react";
import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Empty, Segmented, Skeleton } from "../ui/kit";
import { ActionSheet } from "./action-sheet";
import {
  LeadsError,
  readTasks,
  snoozeTask,
  taskAction,
  type TaskBucket,
  type TaskList,
  type TaskSnoozeChoice,
  type TaskView,
} from "./leads-client";
import { BUCKETS, SNOOZES, bucketLabel, dueWords, kindOf } from "./task-words";
import styles from "./tasks.module.css";

type Loaded = TaskList & { view: TaskBucket; round: number };

/** A write the phone kept counts as made: it goes when Sales X-Ray answers. */
function kept(reason: unknown): reason is LeadsError {
  return reason instanceof LeadsError && reason.kept === true;
}

export function TasksView({
  onOpen,
  now = () => new Date(),
}: {
  onOpen: (leadId: string) => void;
  now?: () => Date;
}) {
  const [view, setView] = useState<TaskBucket>("today");
  const [round, setRound] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  // Taken off this list while the change is on its way (or kept on the phone).
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());
  const [later, setLater] = useState<TaskView | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    readTasks(view, controller.signal).then(
      (list) => setLoaded({ ...list, view, round }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        notify({
          id: "tasks-failed",
          tone: "error",
          title: "Your tasks didn't load",
          message: reason instanceof LeadsError ? reason.message : "Try again.",
        });
      },
    );
    return () => controller.abort();
  }, [view, round]);

  const shown = loaded && loaded.view === view ? loaded : null;
  const tasks = (shown?.tasks ?? []).filter((task) => !gone.has(task.task_id));
  const reload = () => setRound((value) => value + 1);
  const hide = (task: TaskView, hidden: boolean) =>
    setGone((value) => {
      const next = new Set(value);
      if (hidden) next.add(task.task_id);
      else next.delete(task.task_id);
      return next;
    });

  const undo = async (task: TaskView) => {
    try {
      await taskAction(task, "undo");
      hide(task, false);
      reload();
    } catch (reason) {
      if (kept(reason)) return;
      notify({
        id: `task-undo-${task.task_id}`,
        tone: "error",
        title: "Not undone",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    }
  };

  const done = async (task: TaskView) => {
    hide(task, true);
    try {
      const after = await taskAction(task, "done");
      notify({
        id: `task-done-${task.task_id}`,
        tone: "success",
        title: `Done: ${task.title}`,
        action: { label: "Undo", run: () => void undo(after) },
        timeout: 6000,
      });
      reload();
    } catch (reason) {
      if (kept(reason)) {
        notify({
          id: `task-kept-${task.task_id}`,
          tone: "info",
          title: `Done: ${task.title}`,
          message: reason.message,
        });
        return;
      }
      hide(task, false);
      notify({
        id: `task-done-failed-${task.task_id}`,
        tone: "error",
        title: "Not marked done",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    }
  };

  const snooze = async (task: TaskView, choice: TaskSnoozeChoice) => {
    setLater(null);
    hide(task, true);
    try {
      const after = await snoozeTask(task, choice);
      notify({
        id: `task-later-${task.task_id}`,
        tone: "success",
        title: `Moved to ${dueWords(after, now())}`,
        timeout: 4000,
      });
      hide(task, false);
      reload();
    } catch (reason) {
      if (kept(reason)) {
        notify({
          id: `task-kept-${task.task_id}`,
          tone: "info",
          title: "Moved",
          message: reason.message,
        });
        return;
      }
      hide(task, false);
      notify({
        id: `task-later-failed-${task.task_id}`,
        tone: "error",
        title: "Not moved",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    }
  };

  const hour = now().getHours();
  const snoozes = SNOOZES.filter(
    (choice) => choice.key !== "evening" || hour < 17,
  );

  return (
    <section className={styles.tasks} aria-label="Tasks">
      <Segmented
        label="Which tasks"
        items={BUCKETS.map((bucket) => ({
          key: bucket.key,
          label: bucketLabel(bucket, shown?.counts ?? loaded?.counts ?? null),
        }))}
        value={view}
        onChange={setView}
      />
      {!shown ? (
        <ol className={styles.list} aria-busy="true">
          {Array.from({ length: 5 }, (_, index) => (
            <li key={index} className={styles.skeleton}>
              <Skeleton width={32} height={32} />
              <Skeleton width="60%" height={14} />
            </li>
          ))}
        </ol>
      ) : tasks.length === 0 ? (
        <Empty
          icon={ListTodo}
          title={
            view === "overdue"
              ? "Nothing overdue"
              : view === "today"
                ? "Nothing due today"
                : "Nothing coming up"
          }
          text="Add a task from a lead with Remind. It shows here on its day."
        />
      ) : (
        <ol
          className={styles.list}
          aria-label={`${view} tasks, earliest first`}
        >
          {tasks.map((task) => {
            const kind = kindOf(task.kind);
            const Icon = kind.icon;
            return (
              <li key={task.task_id} className={styles.item}>
                <button
                  type="button"
                  className={styles.row}
                  data-lead-row=""
                  onClick={() => onOpen(task.lead_id)}
                >
                  <span
                    className={styles.icon}
                    data-kind={task.kind}
                    aria-hidden="true"
                  >
                    <Icon size={16} />
                  </span>
                  <span className={styles.text}>
                    <strong>{task.title}</strong>
                    <span>
                      {kind.label} · {displayName(task.lead_name)}
                    </span>
                    {task.location ? (
                      <small>
                        <MapPin size={12} aria-hidden="true" /> {task.location}
                      </small>
                    ) : null}
                    {task.note ? <small>{task.note}</small> : null}
                  </span>
                  <time
                    dateTime={task.starts_at}
                    data-late={task.overdue ? "" : undefined}
                  >
                    {dueWords(task, now())}
                  </time>
                </button>
                <span className={styles.acts}>
                  <button
                    type="button"
                    className={styles.act}
                    aria-label={`Later: ${task.title}`}
                    onClick={() => setLater(task)}
                  >
                    <Clock size={18} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className={styles.act}
                    data-done=""
                    aria-label={`Done: ${task.title}`}
                    onClick={() => void done(task)}
                  >
                    <Check size={18} aria-hidden="true" />
                  </button>
                </span>
              </li>
            );
          })}
        </ol>
      )}
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
