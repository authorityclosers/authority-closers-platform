"use client";

/**
 * What your role lets you do in the selected workspace (roles.ts), so a page
 * hides what the server would refuse: plans and prices for those who don't
 * pay, the team's insights for those who don't see the team. Team coaching
 * follows its own server check (coaching/team-coaching-access.ts).
 */
import { useEffect, useSyncExternalStore } from "react";

import { can, type Capability } from "./organisation/roles";
import { useWorkspaceAccess } from "./workspace-access";

/**
 * The last role this browser saw here, the role's name only ("owner",
 * "member"…, or "personal" for a personal workspace), so a screen that opens
 * before the workspace list arrives is drawn for the right person (v1.96
 * device polish, lane P: on slow 3G a seller saw the owner's Settings for
 * 30 s). It only decides while the real role is unknown.
 */
export const LAST_ROLE_KEY = "sx.last-role";
const PERSONAL = "personal";

function readLastRole(): string | null {
  try {
    return window.localStorage.getItem(LAST_ROLE_KEY);
  } catch {
    return null;
  }
}

function rememberRole(role: string): void {
  try {
    if (window.localStorage.getItem(LAST_ROLE_KEY) !== role)
      window.localStorage.setItem(LAST_ROLE_KEY, role);
  } catch {
    // Without storage the next cold start waits for the role, as before.
  }
}

const noChange = () => () => {};

/**
 * can() for the selected workspace. In an organisation your role there
 * decides. A personal workspace is yours alone, its plan too, so it allows
 * everything. While the workspace list loads it answers from the last role
 * this browser saw, else null; outside the app frame (tests, previews)
 * nothing is known to refuse, so it allows.
 */
export function useCanHere(): (capability: Capability) => boolean | null {
  const access = useWorkspaceAccess();
  const here = access?.workspaces?.find(
    (workspace) => workspace.tenant_id === access.context?.tenantId,
  );
  const loading =
    access?.status === "loading" || access?.status === "selecting";
  const known = here
    ? here.kind === "organisation"
      ? (here.role ?? null)
      : PERSONAL
    : null;
  const last = useSyncExternalStore(noChange, readLastRole, () => null);
  useEffect(() => {
    if (known) rememberRole(known);
  }, [known]);
  return (capability) => {
    if (!here) {
      if (!loading) return true;
      if (!last) return null;
      return last === PERSONAL || can(last, capability);
    }
    return here.kind !== "organisation" || can(here.role, capability);
  };
}
