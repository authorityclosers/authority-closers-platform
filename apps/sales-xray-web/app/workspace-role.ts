"use client";

/**
 * What your role lets you do in the selected workspace (roles.ts), so a page
 * hides what the server would refuse: plans and prices for those who don't
 * pay, the team's insights for those who don't see the team. Team coaching
 * follows its own server check (coaching/team-coaching-access.ts).
 */
import { can, type Capability } from "./organisation/roles";
import { useWorkspaceAccess } from "./workspace-access";

/**
 * can() for the selected workspace. In an organisation your role there
 * decides. A personal workspace is yours alone, its plan too, so it allows
 * everything. Null while the workspace list loads; outside the app frame
 * (tests, previews) nothing is known to refuse, so it allows.
 */
export function useCanHere(): (capability: Capability) => boolean | null {
  const access = useWorkspaceAccess();
  const here = access?.workspaces?.find(
    (workspace) => workspace.tenant_id === access.context?.tenantId,
  );
  const loading =
    access?.status === "loading" || access?.status === "selecting";
  return (capability) => {
    if (!here) return loading ? null : true;
    return here.kind !== "organisation" || can(here.role, capability);
  };
}
