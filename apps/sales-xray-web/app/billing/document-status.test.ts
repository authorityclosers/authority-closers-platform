import { expect, it } from "vitest";

import type { Refund } from "./contract";
import { documentStatus } from "./document-status";

const refund = (state: Refund["state"]): Refund => ({
  paymentId: "pay_fictional",
  refundableUntil: "2026-10-30T09:00:00Z",
  state,
  reasonCode: null,
});

it("says a refunded payment's invoice was refunded", () => {
  expect(documentStatus({ status: "Issued", refund: refund("refunded") })).toBe(
    "Refunded",
  );
  expect(documentStatus({ status: "Issued", refund: refund("pending") })).toBe(
    "Refund requested",
  );
});

it("keeps the invoice's own status otherwise", () => {
  expect(
    documentStatus({ status: "Issued", refund: refund("available") }),
  ).toBe("Issued");
  expect(documentStatus({ status: "Issued", refund: null })).toBe("Issued");
  expect(documentStatus({ status: "Issued" })).toBe("Issued");
});
