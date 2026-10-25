/**
 * The team engine's screens (Lead OS 9036d1a85 and 433fc8247): share leads out
 * by a rule, set each seller's targets, turn nudges on. Owners and managers.
 */

import type { Metric, MetricProgress } from "../dashboard/my-day-client";
import { deskJson, deskRequest, type Team } from "./leads-client";

export type ShareRule = "even" | "balanced" | "by_source" | "by_city";

export type ShareCommand = {
  command_id: string;
  lead_ids?: string[];
  unassigned?: boolean;
  rule: ShareRule;
  sellers?: string[];
  groups?: Record<string, string[]>;
  spread_all?: boolean;
  preview: boolean;
};

export type Distribution = {
  rule: ShareRule;
  preview: boolean;
  leads: number;
  moved: number;
  given: {
    person_id: string;
    name: string;
    leads: number;
    open_after: number;
    max_open: number;
  }[];
  /** Leads left where they are, by why. */
  left: Partial<
    Record<
      | "closed"
      | "already_theirs"
      | "no_seller_for_it"
      | "everyone_at_cap"
      | "gone",
      number
    >
  >;
  sources: Record<string, number>;
  cities: Record<string, number>;
  more: boolean;
  words: string;
};

const PATH = "/v1/lead-desk";

/**
 * A preview changes nothing, so it goes straight to the server (never into the
 * phone's queue of writes that wait for a connection).
 */
export async function previewShare(
  command: ShareCommand,
  signal?: AbortSignal,
): Promise<Distribution> {
  const response = await fetch(`${PATH}/leads/distribute`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ ...command, preview: true }),
  });
  if (!response.ok) throw new Error(`share_preview_${response.status}`);
  return (await response.json()) as Distribution;
}

/** Give the leads out; the same command id again returns the first result. */
export function applyShare(command: ShareCommand) {
  return deskRequest<Distribution>(
    "/leads/distribute",
    deskJson("POST", { ...command, preview: false }),
  );
}

export type TargetLine = {
  metric: Metric;
  period: "day" | "week";
  value: number;
};

export type SellerTargets = {
  person_id: string;
  targets: TargetLine[];
  progress: MetricProgress[];
};

export function readTeamTargets(signal?: AbortSignal) {
  return deskRequest<{ sellers: SellerTargets[] }>("/targets/team", {
    signal,
  });
}

/** From today on; a value of 0 removes that target. */
export function saveTargets(
  personId: string,
  targets: TargetLine[],
  commandId: string,
) {
  return deskRequest<SellerTargets>(
    "/targets",
    deskJson("PUT", { command_id: commandId, person_id: personId, targets }),
  );
}

export type NudgeSettings = Team["settings"] & {
  nudges?: boolean;
  nudges_off_for?: string[];
};

export function saveNudges(
  expectedRevision: number,
  enabled: boolean,
  offFor: string[],
) {
  return deskRequest<Team>(
    "/nudges",
    deskJson("PUT", {
      expected_revision: expectedRevision,
      enabled,
      off_for: offFor,
    }),
  );
}

/** The words on the seller's latest nudge (the app plays its own sound). */
export function readNudge(signal?: AbortSignal) {
  return deskRequest<{
    title: string;
    body: string;
    url: string;
    urgency?: "urgent" | null;
  }>("/alert?kind=nudge", { signal });
}

const LEFT_WORDS: Record<keyof Distribution["left"], [string, string]> = {
  closed: ["is closed", "are closed"],
  already_theirs: [
    "is already with that seller",
    "are already with those sellers",
  ],
  no_seller_for_it: [
    "has no seller picked for it",
    "have no seller picked for them",
  ],
  everyone_at_cap: [
    "waits: everyone is at their limit",
    "wait: everyone is at their limit",
  ],
  gone: ["is gone", "are gone"],
};

/** "3 are closed", "2 wait: everyone is at their limit". */
export function leftWords(left: Distribution["left"]): string[] {
  return (Object.keys(LEFT_WORDS) as (keyof Distribution["left"])[])
    .filter((key) => left[key])
    .map((key) => {
      const count = left[key] ?? 0;
      return `${count} ${LEFT_WORDS[key][count === 1 ? 0 : 1]}`;
    });
}
