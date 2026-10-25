/**
 * Organisation roles (Roles B, 25 Oct 2026; the server's tenancy/roles.py): their names
 * and one line on what each may do, for Members, a person's page and invitations.
 * Sellers keep the stored value "member".
 */
import { ORG_ROLES, type OrgRole } from "./organisation-api";
// A copy of the server's map (tenancy/roles.py CAPABILITIES); a Python test fails when
// they differ (tests/unit/tenancy/test_roles.py).
import CAPABILITIES from "./role-capabilities.json";

export type Capability =
  | "org.manage"
  | "members.manage"
  | "billing.view"
  | "billing.pay"
  | "team.view"
  | "leads.manage"
  | "leads.delete"
  | "leads.work";

const MAP: Record<string, readonly string[]> = CAPABILITIES;

/** Whether a member with this role may do this; unknown roles may do nothing. */
export function can(
  role: string | null | undefined,
  capability: Capability,
): boolean {
  return (
    typeof role === "string" &&
    Object.prototype.hasOwnProperty.call(MAP, role) &&
    MAP[role].includes(capability)
  );
}

export const ROLE_LABEL: Record<OrgRole, string> = {
  owner: "Owner",
  admin: "Admin",
  manager: "Sales manager",
  member: "Seller",
  viewer: "Viewer",
  finance: "Finance",
};

export const ROLE_HINT: Record<OrgRole, string> = {
  owner: "Everything, including passing ownership on.",
  admin: "Runs the workspace: members, settings, apps and leads.",
  manager: "The team's leads, calls and reports. No settings or billing.",
  member: "Their own leads, calls and tasks.",
  viewer: "Sees the team's work and changes nothing.",
  finance: "Billing only.",
};

/** A role's name; an unknown one reads as Seller, as members did before. */
export const roleLabel = (role: string | null | undefined): string =>
  ORG_ROLES.includes(role as OrgRole)
    ? ROLE_LABEL[role as OrgRole]
    : ROLE_LABEL.member;

/** What an owner may give (every role but owner), and an admin (not admin either). */
export const rolesToGive = (isOwner: boolean): OrgRole[] =>
  ORG_ROLES.filter((role) => role !== "owner" && (isOwner || role !== "admin"));
