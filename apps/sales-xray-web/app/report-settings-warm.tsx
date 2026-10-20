"use client";

import { useEffect } from "react";

import { identityOf } from "./calls-cache";
import { loadReportSettings } from "./report-settings";
import { useWorkspaceAccess } from "./workspace-access";

/**
 * Asks for this workspace's report settings version as a call page opens,
 * beside the call's own reads, so its Report paints in that version straight
 * away (one read per workspace; the Report reuses it).
 */
export function ReportSettingsWarmUp() {
  const access = useWorkspaceAccess();
  const signedIn = access?.authenticated === true && access.status === "ready";
  const identity = identityOf(access?.context ?? null);
  useEffect(() => {
    if (signedIn) void loadReportSettings(identity);
  }, [signedIn, identity]);
  return null;
}
