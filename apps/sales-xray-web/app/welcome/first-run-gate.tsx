"use client";

import { useEffect } from "react";

import { readCallSummary } from "../dashboard/dashboard-data";
import { useWorkspaceAccess } from "../workspace-access";
import {
  forgetFreshSignIn,
  freshSignIn,
  markSetup,
  needsSetup,
  readSetupMark,
  WELCOME_PATH,
} from "./setup-state";

/**
 * On Home, right after a sign-in: a brand-new account (no organisation, no
 * calls) goes to /welcome once. Everyone else, and every later visit, stays.
 */
export function FirstRunGate() {
  const access = useWorkspaceAccess();
  const personId =
    access?.authenticated === true && access.status === "ready"
      ? access.context?.personId
      : undefined;
  const organisations = access?.workspaces
    ? access.workspaces.filter((item) => item.kind === "organisation").length
    : null;

  useEffect(() => {
    if (!personId || organisations === null || !freshSignIn()) return;
    if (readSetupMark(personId) !== null || organisations > 0) {
      if (organisations > 0) markSetup(personId, "not-needed");
      forgetFreshSignIn();
      return;
    }
    const controller = new AbortController();
    void readCallSummary(controller.signal)
      .then((summary) => {
        if (controller.signal.aborted) return;
        forgetFreshSignIn();
        const calls = summary?.total ?? null;
        if (needsSetup({ organisations, calls }))
          window.location.replace(WELCOME_PATH);
        else if (calls !== null) markSetup(personId, "not-needed");
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [personId, organisations]);

  return null;
}
