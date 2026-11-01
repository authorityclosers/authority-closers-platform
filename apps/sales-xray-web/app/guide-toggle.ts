"use client";

import { useMemo, useSyncExternalStore } from "react";

import { GuideProgressStore } from "./guide-progress";
import { FIRST_CALL_GUIDE } from "./guide-registry";
import { notify } from "./notice-center";
import { useWorkspaceAccess } from "./workspace-access";

const idle = () => () => {};
const none = () => null;

/**
 * The account-menu switch for the first-call guide (owner, 5 Oct 2026).
 * Off once closed, skipped or finished; turning it on restarts at step one,
 * and says where it opens, New analysis, with a way there (phone personas
 * ph1-51, 1 Nov 2026: turning it on closed the menu and nothing happened).
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
      if (on)
        notify({
          id: "first-call-guide",
          tone: "info",
          title: "First call guide is on",
          message: "It opens on New analysis, where you add a call.",
          action: {
            label: "Open New analysis",
            href: "/analysis/new",
            run: () => {},
            icon: "none",
          },
          timeout: 10_000,
        });
    },
  };
}
