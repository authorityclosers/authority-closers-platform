"use client";

import { useEffect } from "react";

import { readCallSummary } from "../dashboard/dashboard-data";
import { useWorkspaceAccess } from "../workspace-access";
import {
  forgetFreshSignIn,
  freshSignIn,
  holdFirstRun,
  markSetup,
  needsPick,
  needsSetup,
  PICK_PATH,
  readSetupMark,
  WELCOME_PATH,
} from "./setup-state";

/**
 * On Home, right after a sign-in: someone with two or more workspaces is asked
 * where to work (/welcome?pick=1); a brand-new account (no organisation, no
 * calls) goes to /welcome once. Everyone else, and every later visit, stays.
 * While it decides, the page carries data-sx-first-run, so "Set up this phone"
 * waits and the two never open together (one flow, owner 25 Oct 2026).
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
  const enabled = access?.workspaces
    ? access.workspaces.filter((item) => item.sales_xray_enabled).length
    : null;

  useEffect(() => {
    if (!personId || organisations === null || !freshSignIn()) return;
    holdFirstRun(true);
    if (needsPick(enabled ?? 0)) {
      forgetFreshSignIn();
      window.location.replace(PICK_PATH);
      return;
    }
    if (readSetupMark(personId) !== null || organisations > 0) {
      if (organisations > 0) markSetup(personId, "not-needed");
      forgetFreshSignIn();
      holdFirstRun(false);
      return;
    }
    const controller = new AbortController();
    void readCallSummary(controller.signal)
      .then((summary) => {
        if (controller.signal.aborted) return;
        forgetFreshSignIn();
        const calls = summary?.total ?? null;
        if (needsSetup({ organisations, calls })) {
          window.location.replace(WELCOME_PATH);
          return;
        }
        if (calls !== null) markSetup(personId, "not-needed");
        holdFirstRun(false);
      })
      .catch(() => holdFirstRun(false));
    return () => {
      controller.abort();
      holdFirstRun(false);
    };
  }, [personId, organisations, enabled]);

  return null;
}
