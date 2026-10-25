/**
 * Organisation roles (Roles B, 25 Oct 2026; the server's tenancy/roles.py): their names
 * and one line on what each may do, for Members, a person's page and invitations.
 * Sellers keep the stored value "member".
 */
import { ORG_ROLES, type OrgRole } from "./organisation-api";

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

/** What an owner may give (every role but owner), and an admin (not admin either). */
export const rolesToGive = (isOwner: boolean): OrgRole[] =>
  ORG_ROLES.filter((role) => role !== "owner" && (isOwner || role !== "admin"));
