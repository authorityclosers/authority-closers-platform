"use client";

import { useMemo, useSyncExternalStore } from "react";

import { GuideProgressStore } from "./guide-progress";
import { FIRST_CALL_GUIDE } from "./guide-registry";
import { useWorkspaceAccess } from "./workspace-access";

const idle = () => () => {};
const none = () => null;

/**
 * The account-menu switch for the first-call guide (owner, 5 Oct 2026).
 * Off once closed, skipped or finished; turning it on restarts at step one.
 */
export function useFirstCallGuideSwitch() {
  const access = useWorkspaceAccess();
  const personId =
    access?.authenticated === true ? access.context?.personId : undefined;
  const store = useMemo(
    () =>
      personId ? new GuideProgressStore(personId, FIRST_CALL_GUIDE) : null,
    [personId],
  );
  const progress = useSyncExternalStore(
    store?.subscribe ?? idle,
    store?.getSnapshot ?? none,
    none,
  );
  if (!store || !progress) return null;
  return {
    on: progress.status === "active",
    set(on: boolean) {
      store.update({
        stepId: FIRST_CALL_GUIDE.steps[0]?.id ?? "",
        status: on ? "active" : "skipped",
      });
    },
  };
}
