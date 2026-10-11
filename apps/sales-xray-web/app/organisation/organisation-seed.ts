import type { ServerRead } from "../server-reads";
import {
  parseActivity,
  parseMembers,
  parseOrganisation,
  type OrgActivity,
  type OrgMember,
  type Organisation,
} from "./organisation-api";

/** The page's first reads, exactly as the browser makes them. */
export const ORGANISATION_PATHS = {
  organisation: "/v1/organisation",
  members: "/v1/organisation/members",
  activity: "/v1/organisation/activity?days=30",
} as const;

export type ServerOrganisation = Readonly<
  Partial<Record<keyof typeof ORGANISATION_PATHS, ServerRead>>
>;

export type OrganisationSeed = {
  organisation?: Organisation;
  members?: OrgMember[];
  activity?: OrgActivity;
};

function parsed<T>(
  read: ServerRead | undefined,
  parse: (value: unknown) => T,
): T | undefined {
  if (read?.status !== 200) return undefined;
  try {
    return parse(read.body);
  } catch {
    return undefined;
  }
}

/**
 * The server's answers as the page's first values: only successes with the
 * browser read's own shape. Anything else (no answer, Personal, an error, a
 * bad shape) is read in the browser as before.
 */
export function seededOrganisation(
  initial: ServerOrganisation | null | undefined,
): OrganisationSeed {
  return {
    organisation: parsed(initial?.organisation, parseOrganisation),
    members: parsed(initial?.members, parseMembers),
    activity: parsed(initial?.activity, parseActivity),
  };
}
