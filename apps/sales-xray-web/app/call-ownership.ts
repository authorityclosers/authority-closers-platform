import { displayName } from "./display-name";

/**
 * Who may change a call. The server lets only a call's owner rename or delete
 * it; organisation owners and admins may read members' calls, not edit them.
 *
 * Lists read with `?include_owners=true` carry an owner only where the viewer
 * can see other people's calls. A row without an owner is the viewer's own.
 */
export function ownsCall(
  owner: { personId: string } | undefined,
  viewerId: string | null,
): boolean {
  if (!owner) return true;
  return viewerId !== null && owner.personId === viewerId;
}

/** "You" for the viewer's own calls, otherwise the owner's name. */
export function ownerLabel(
  owner: { personId: string; name: string },
  viewerId: string | null,
): string {
  return ownsCall(owner, viewerId) ? "You" : displayName(owner.name);
}

/** Fired to switch workspace from outside the sidebar (the shell owns it). */
export const SELECT_WORKSPACE_EVENT = "sales-xray:select-workspace";

/** `next` lands on that page of the workspace instead of reloading this one. */
export function requestWorkspace(tenantId: string, next?: string) {
  window.dispatchEvent(
    new CustomEvent(SELECT_WORKSPACE_EVENT, {
      detail: next ? { tenantId, next } : tenantId,
    }),
  );
}
