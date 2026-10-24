/**
 * Lead OS card and sheet words (pure, tested): what a card says about the
 * last contact and the next step, how long a lead has sat in its stage, and
 * what the stage sheet's button says.
 */

import { ago, when, type LeadRow } from "../leads-client";
import type { LeadKind } from "../../telemetry";
import type { MoveOption } from "./pipeline-client";

export type NextTone = "late" | "none" | "today" | "later" | "closed";

/** The card's next step: late (red), no next step (amber), today, later. */
export function nextStep(
  lead: Pick<
    LeadRow,
    "next_action_at" | "overdue" | "no_next_action" | "group" | "stage"
  >,
  now: Date = new Date(),
): { tone: NextTone; text: string } {
  if (lead.group && lead.group !== "active")
    return { tone: "closed", text: "" };
  if (lead.no_next_action) return { tone: "none", text: "No next step" };
  if (!lead.next_action_at)
    return lead.stage === "new"
      ? { tone: lead.overdue ? "late" : "today", text: "Call now" }
      : { tone: "none", text: "No next step" };
  const at = new Date(lead.next_action_at);
  if (lead.overdue) {
    const late = ago(lead.next_action_at, now).replace(" ago", "");
    return { tone: "late", text: `Late ${late}` };
  }
  const text = when(lead.next_action_at, now);
  const sameDay = at.toDateString() === now.toDateString();
  return {
    tone: sameDay ? "today" : "later",
    text: text.charAt(0).toUpperCase() + text.slice(1),
  };
}

/** "Called 2 h ago", or how long since it came in. */
export function lastContact(
  lead: Pick<LeadRow, "last_contact_at" | "created_at">,
  now: Date = new Date(),
): string {
  if (lead.last_contact_at)
    return `Last contact ${ago(lead.last_contact_at, now)}`;
  return `Came in ${ago(lead.created_at, now)}`;
}

/** The card's one time: when the lead was last heard from (or came in); once it has
 *  sat in its stage longer than the stage allows, how long it has been there, in words
 *  as well as in amber. */
export function cardTime(
  lead: Pick<LeadRow, "last_contact_at" | "created_at" | "stage_at" | "group">,
  rotHours: number | null | undefined,
  now: Date = new Date(),
): { text: string; old: boolean } {
  if (lead.stage_at && rotting(lead, rotHours, now))
    return {
      text: `${ago(lead.stage_at, now).replace(" ago", "")} in stage`,
      old: true,
    };
  return {
    text: ago(lead.last_contact_at ?? lead.created_at, now),
    old: false,
  };
}

/** Whether a lead has sat in its stage longer than the stage allows. */
export function rotting(
  lead: Pick<LeadRow, "stage_at" | "group">,
  rotHours: number | null | undefined,
  now: Date = new Date(),
): boolean {
  if (!rotHours || !lead.stage_at || (lead.group && lead.group !== "active"))
    return false;
  return now.getTime() - Date.parse(lead.stage_at) > rotHours * 3_600_000;
}

/** The sheet's one button: says what the move does. */
export function moveVerb(
  move: Pick<MoveOption, "action" | "group" | "label" | "needs">,
) {
  if (move.action === "reopen") return `Reopen in ${move.label}`;
  if (move.group === "won") return "Close as Won";
  if (move.group === "lost")
    return move.action === "reclassify" ? "Move to Lost" : "Close as Lost";
  if (move.group === "junk") return "Mark as Junk";
  if (move.needs.includes("meeting")) return "Book meeting";
  return `Move to ${move.label}`;
}

/** One line under a final outcome's button. */
export function finalLine(move: Pick<MoveOption, "group">): string | null {
  if (move.group === "won")
    return "It leaves the follow-ups. You can reopen it later.";
  if (move.group === "lost")
    return "A real lead who said no. It leaves the follow-ups; you can reopen it.";
  if (move.group === "junk")
    return "Fake or unusable. Kept apart from Lost, out of your numbers.";
  return null;
}

const KINDS = new Set<LeadKind>([
  "new",
  "not_connected",
  "follow_up",
  "interested",
  "won",
  "lost",
  "junk",
]);

/** A stage kind as telemetry takes it (never the business's own label). */
export function leadKind(
  kind: string | null | undefined,
): LeadKind | undefined {
  return kind && KINDS.has(kind as LeadKind) ? (kind as LeadKind) : undefined;
}

/** A phone number with only its last four digits: ••4321. */
export function maskedPhone(last4: string | null | undefined): string | null {
  return last4 ? `••${last4}` : null;
}
