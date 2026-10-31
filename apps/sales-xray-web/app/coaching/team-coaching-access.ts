"use client";

import type { SalesXrayWorkspace } from "../sales-xray-workspaces";
import { useWorkspaceAccess } from "../workspace-access";

/**
 * Whether the server answers Team coaching here, and a teammate's coaching:
 * only for an active owner or admin of an organisation. This mirrors
 * conversation_intelligence/guest_ownership.py
 * GuestOwnership.organisation_call_reader, which coaching/library.py
 * read_team and read_shared ask, and coaching/http.py sandbox_for asks the
 * same of the AC Sandbox. No roles.ts capability says exactly this (it is
 * narrower than "team.view"), so the roles are named here as the server
 * names them. Managers, viewers and sellers read their own coaching. Null
 * while the workspace isn't known; the server still decides every read.
 */
export function teamCoachingFor(
  workspace: Pick<SalesXrayWorkspace, "kind" | "role"> | undefined,
): boolean | null {
  if (!workspace) return null;
  return (
    workspace.kind === "organisation" &&
    (workspace.role === "owner" || workspace.role === "admin")
  );
}

/** teamCoachingFor() the selected workspace. */
export function useTeamCoachingHere(): boolean | null {
  const access = useWorkspaceAccess();
  return teamCoachingFor(
    access?.workspaces?.find(
      (workspace) => workspace.tenant_id === access.context?.tenantId,
    ),
  );
}
