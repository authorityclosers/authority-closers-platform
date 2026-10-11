import { expect, it } from "vitest";
import { parseHumanCallOutcome } from "./report-call-outcome-contract";

it.each([
  { outcome: "won" },
  { outcome: "no_decision" },
  { outcome: "lost", lost_reason: "  Chose another option.  " },
  { outcome: "follow_up", follow_up_on: "2026-10-12" },
  { outcome: "follow_up", follow_up_on: "2028-02-29" },
  {
    outcome: "won",
    deal_value: { amount: "125000.0000", currency_code: "INR" },
  },
  { outcome: "no_decision", deal_value: { amount: "0", currency_code: "USD" } },
])(
  "retains explicit human values without inference or rounding %#",
  (value) => {
    const parsed = parseHumanCallOutcome(value);
    expect(parsed).toMatchObject(value);
    expect(parseHumanCallOutcome(parsed)).toEqual(parsed);
  },
);
it.each([
  null,
  {},
  { outcome: "unknown" },
  { outcome: "won", basis: "heard_in_call" },
  { outcome: "won", created_by: "another person" },
  { outcome: "lost" },
  { outcome: "lost", lost_reason: " " },
  { outcome: "lost", lost_reason: "private\0reason" },
  { outcome: "lost", lost_reason: "x".repeat(1001) },
  { outcome: "won", lost_reason: "private reason" },
  { outcome: "follow_up" },
  { outcome: "follow_up", follow_up_on: "2026-02-30" },
  { outcome: "follow_up", follow_up_on: "0000-10-12" },
  { outcome: "follow_up", follow_up_on: "20261012" },
  { outcome: "follow_up", follow_up_on: "2026-10-12T10:00:00Z" },
  { outcome: "won", follow_up_on: "2026-10-12" },
  { outcome: "won", deal_value: { amount: 10, currency_code: "INR" } },
  { outcome: "won", deal_value: { amount: "NaN", currency_code: "INR" } },
  { outcome: "won", deal_value: { amount: "1e5", currency_code: "INR" } },
  { outcome: "won", deal_value: { amount: "-1", currency_code: "INR" } },
  { outcome: "won", deal_value: { amount: "1.00001", currency_code: "INR" } },
  {
    outcome: "won",
    deal_value: { amount: "10000000000000000", currency_code: "INR" },
  },
  { outcome: "won", deal_value: { amount: "10" } },
  { outcome: "won", deal_value: { amount: "10", currency_code: "inr" } },
  {
    outcome: "won",
    deal_value: { amount: "10", currency_code: "INR", scale: "lakh" },
  },
])("rejects malformed facts without leaking private input %#", (value) => {
  expect(() => parseHumanCallOutcome(value)).toThrow(
    "Enter a valid call outcome.",
  );
});
