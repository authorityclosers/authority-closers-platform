import { withDisplayNames } from "../display-name";
import {
  SERVER_READ_BUDGET_MS,
  serverApiOrigin,
  serverReads,
  SESSION_PATHS,
} from "../server-reads";
import type { Desk, LeadPage } from "./leads-client";
import type { ServerLeads } from "./leads-seed";

const DESK = "/v1/lead-desk";
const NAMES = new Set(["name", "owner_name", "actor_name"]);
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

/**
 * The ordinary desk and first list page before browser startup. Full document
 * requests only; the existing server reader forwards this request's own cookie,
 * limits the wait and never caches private answers. Other filters use the client.
 */
export async function serverLeads(
  searchParams: Promise<Record<string, string | string[] | undefined>>,
): Promise<ServerLeads | null> {
  if (!serverApiOrigin()) return null;
  const params = await searchParams;
  // To call may remember a pipeline in this browser. Keep that existing path;
  // this seed covers only the unfiltered All leads entry reported in #67.
  if (
    params.tab !== "all" ||
    (params.stage !== undefined && params.stage !== "open") ||
    Object.keys(params).some((key) => !["tab", "stage", "theme"].includes(key))
  )
    return null;
  // Both reads share one budget: the page never waits longer for them.
  const deadline = Date.now() + SERVER_READ_BUDGET_MS;
  const reads = await serverReads(
    [...SESSION_PATHS, DESK],
    SERVER_READ_BUDGET_MS,
  );
  if (
    SESSION_PATHS.some((path) => reads?.[path]?.status !== 200) ||
    reads?.[DESK]?.status !== 200
  )
    return null;
  const person = record(reads[SESSION_PATHS[0]]?.body);
  const directory = record(reads[SESSION_PATHS[1]]?.body);
  const desk = reads[DESK]!.body as Desk;
  const tenant = directory.selected_tenant_id;
  if (
    typeof person.person_id !== "string" ||
    typeof person.session_id !== "string" ||
    typeof tenant !== "string" ||
    person.selected_tenant_id !== tenant ||
    desk?.me?.person_id !== person.person_id ||
    !Array.isArray(desk.queue) ||
    typeof desk.counts?.open !== "number" ||
    typeof desk.numbers?.calls !== "number"
  )
    return null;
  const identity = JSON.stringify([
    person.person_id,
    person.session_id,
    tenant,
  ]);
  const scope = desk.me.can_manage ? "team" : "mine";
  const path = `/v1/lead-desk/leads?scope=${scope}&stage=open`;
  const left = deadline - Date.now();
  // None left: the desk comes with the page and the browser reads the list.
  const list = left > 0 ? await serverReads([path], left) : null;
  const answer = list?.[path];
  const page = answer?.body as LeadPage | null;
  return {
    identity,
    desk: withDisplayNames(desk, NAMES),
    firstPage:
      answer?.status === 200 &&
      Array.isArray(page?.leads) &&
      typeof page.total === "number"
        ? { scope, page: withDisplayNames(page, NAMES) }
        : null,
  };
}
