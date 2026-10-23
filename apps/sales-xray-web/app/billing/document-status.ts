import type { BillingDocument } from "./billing-view";

/** A refunded payment's invoice says so, rather than "Issued" (QA, 23 Oct 2026). */
export function documentStatus(
  document: Pick<BillingDocument, "status" | "refund">,
): string {
  if (document.refund?.state === "refunded") return "Refunded";
  if (document.refund?.state === "pending") return "Refund requested";
  return document.status;
}
