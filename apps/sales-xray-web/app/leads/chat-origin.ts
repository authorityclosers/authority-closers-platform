/**
 * Leads that started as a chat (WhatsApp, Messenger, Instagram) have no form:
 * what the server keeps for them is Meta's own person id, which means nothing
 * to a seller (orchestrator's dev pass, 20 Oct: "ANSWERS FROM THE FORM" with a
 * raw Messenger id). These helpers name the chat instead and leave the id out.
 */

import type { LeadRow } from "./leads-client";

export type ChatOrigin = "whatsapp" | "messenger" | "instagram";

const ORIGINS: [RegExp, ChatOrigin][] = [
  [/^WhatsApp · /, "whatsapp"],
  [/^Messenger · /, "messenger"],
  [/^Instagram · /, "instagram"],
];

/** The chat a lead came from, read from where the CRM filed it. */
export function chatOrigin(
  lead: Pick<LeadRow, "source" | "source_label">,
): ChatOrigin | null {
  if (lead.source !== "webhook") return null;
  return (
    ORIGINS.find(([pattern]) => pattern.test(lead.source_label))?.[1] ?? null
  );
}

const ID_LABELS = /^(messenger|instagram|whatsapp|name|phone)$/i;

/**
 * What is worth showing from a chat lead's record: never Meta's ids, the name
 * or phone (shown above already); "came from: comment" in plain words.
 */
export function chatFacts(
  fields: { label: string; value: string }[],
): { label: string; value: string }[] {
  return fields
    .filter(
      (field) => !ID_LABELS.test(field.label) && !/^\d{6,}$/.test(field.value),
    )
    .map((field) =>
      /^came from$/i.test(field.label) && field.value === "comment"
        ? { label: "Came from", value: "A comment on your post" }
        : field,
    );
}
