"use client";

/**
 * "A task was added": every task list on screen reads again at once (owner,
 * bug reports 218 and 219, 15 Nov 2026: a task added from the header's + "isn't
 * showing up here until refresh", on Home and on Tasks). The Add task sheet
 * says it whichever screen opened it; Home's and Tasks' lists listen.
 */

import { useEffect, useRef } from "react";

export const TASKS_CHANGED_EVENT = "sx:tasks-changed";

/** Tell the task lists on screen to read again. */
export function tasksChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(TASKS_CHANGED_EVENT));
}

/** Run `reread` whenever a task is added anywhere in the app. */
export function useTasksChanged(reread: () => void): void {
  const latest = useRef(reread);
  useEffect(() => {
    latest.current = reread;
  });
  useEffect(() => {
    const listen = () => latest.current();
    window.addEventListener(TASKS_CHANGED_EVENT, listen);
    return () => window.removeEventListener(TASKS_CHANGED_EVENT, listen);
  }, []);
}
