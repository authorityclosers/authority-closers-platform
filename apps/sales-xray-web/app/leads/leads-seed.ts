import type { Desk, LeadPage } from "./leads-client";
import { OPENING_STAGE } from "./opening";

/** The normal API's first answers for this document, bound to its identity. */
export type ServerLeads = {
  identity: string;
  desk: Desk;
  firstPage: { scope: "team" | "mine"; page: LeadPage } | null;
};

/** A server seed never answers a different person, session, workspace or filter. */
export function firstPageFor(
  seed: ServerLeads | null | undefined,
  identity: string | null | undefined,
  ask: {
    scope: string;
    stage: string;
    query: string;
    pipeline?: string | null;
    owner?: string | null;
    more?: object | null;
  },
): LeadPage | null {
  return seed?.firstPage &&
    seed.identity === identity &&
    seed.firstPage?.scope === ask.scope &&
    ask.stage === OPENING_STAGE &&
    !ask.query &&
    !ask.pipeline &&
    !ask.owner &&
    !Object.values(ask.more ?? {}).some(Boolean)
    ? seed.firstPage.page
    : null;
}
