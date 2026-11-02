/**
 * Bulk upload's choices (stages-views-sources.md section 5, owner + Dipak, 30 Oct 2026):
 * where new leads go (Cold Leads by default, or Inbound Leads), who receives them and how
 * many each, and the stage they start in. Apart from the screen, so they are tested alone.
 */

import type { ImportPreview, RepView } from "./leads-client";
import type { StageView } from "./journey/journey-client";

export type Side = "cold" | "live";
/** Who gets the new leads (owner, 2 Nov 2026: "Who gets these leads?"): shared between
 *  the sellers, one seller, or left for the owner to assign; a seller's go on their own
 *  desk ("me"). "rules" is the lead rules, kept for older callers. */
export type Recipients = "people" | "one" | "rules" | "me" | "none";

export type UploadChoices = {
  side: Side;
  assign: Recipients;
  /** "One seller": who. */
  one?: string | null;
  /** Salespeople turned off in the list. */
  off: string[];
  /** Counts the owner typed; null: an even split among those on. */
  counts: Record<string, number> | null;
  /** The stage new leads start in; "": the first. */
  step: string;
};

/** Cold Leads, and for owners and admins an even split among the sellers
 *  (competitor teardown 5, 1 Nov 2026); a seller's go on their own desk. */
export const firstChoices = (canManage: boolean): UploadChoices => ({
  side: "cold",
  assign: canManage ? "people" : "me",
  off: [],
  counts: null,
  step: "",
});

/** About how many rows become new leads: rows that make a lead, less the ones already
 *  leads and the repeats inside the file. */
export function freshRows(preview: ImportPreview): number {
  return Math.max(
    0,
    (preview.importable ?? preview.total_rows) -
      (preview.known_leads ?? 0) -
      preview.repeats_in_file,
  );
}

/** The new leads split evenly, the first people taking one more when they don't divide. */
export function evenSplit(
  total: number,
  ids: string[],
): Record<string, number> {
  const out: Record<string, number> = {};
  if (!ids.length) return out;
  const each = Math.floor(total / ids.length);
  ids.forEach((id, index) => {
    out[id] = each + (index < total % ids.length ? 1 : 0);
  });
  return out;
}

/** Each salesperson's count as the list shows it. */
export function countsFor(
  choices: UploadChoices,
  team: RepView[],
  fresh: number,
): Record<string, number> {
  if (choices.assign === "one")
    return choices.one && team.some((rep) => rep.person_id === choices.one)
      ? { [choices.one]: fresh }
      : {};
  const on = team
    .map((rep) => rep.person_id)
    .filter((id) => !choices.off.includes(id));
  if (choices.counts === null) return evenSplit(fresh, on);
  return Object.fromEntries(on.map((id) => [id, choices.counts?.[id] ?? 0]));
}

/** Who gets how many, for the server, in the list's order; nobody with none. */
export function sharesFor(
  choices: UploadChoices,
  team: RepView[],
  fresh: number,
): { person_id: string; count: number }[] {
  const counts = countsFor(choices, team, fresh);
  return team
    .filter((rep) => (counts[rep.person_id] ?? 0) > 0)
    .map((rep) => ({ person_id: rep.person_id, count: counts[rep.person_id] }));
}

/** The stages a bulk upload may start in: the first, then the in-talks and interested
 *  ones (Open Leads, Interested); never a meeting, a later step, Won, Lost or Junk. */
export function startStages(stages: StageView[]): StageView[] {
  const live = stages.filter((stage) => !stage.archived);
  return live.filter(
    (stage, index) =>
      index === 0 ||
      stage.kind === "follow_up" ||
      (stage.kind === "interested" && stage.milestone === "qualified"),
  );
}

/** The sellers new leads are shared between: those who take new leads. Owners and admins
 *  are among them only once they switched "Taking new leads" on (owner, 2 Nov 2026). */
export function sellersOf(team: RepView[]): RepView[] {
  return team.filter((rep) => rep.available);
}

/** Whether these choices give leads to people the owner picked (shares). */
export const sharing = (assign: Recipients): boolean =>
  assign === "people" || assign === "one";

/** The server's word for these choices: "One seller" is a share of all of them. */
export const serverAssign = (
  assign: Recipients,
): "people" | "rules" | "me" | "none" => (assign === "one" ? "people" : assign);
