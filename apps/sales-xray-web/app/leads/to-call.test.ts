import { expect, it } from "vitest";

import { toCallNow } from "./desk-view";
import { deskSections, type LeadRow } from "./leads-client";

// The To call tab, the badge and the rows tell one story (Redmi, 23 Oct 2026: the
// tab said 0 while Call back and Later today listed the same lead).
const row = (id: string, overrides: Partial<LeadRow> = {}): LeadRow =>
  ({
    lead_id: id,
    why_kind: "due",
    overdue: false,
    ...overrides,
  }) as LeadRow;

it("lists a lead waiting for a call back once, under Call back only", () => {
  const callBack = [row("a")];
  const sections = deskSections(
    [row("a", { why_kind: "later" }), row("b", { why_kind: "later" })],
    callBack,
  );
  expect(
    sections.map((section) => section.rows.map((item) => item.lead_id)),
  ).toEqual([["b"]]);
});

it("counts leads to call now once each: call backs and those due", () => {
  expect(
    toCallNow({
      call_back: [row("a")],
      queue: [
        row("a", { why_kind: "later" }),
        row("b", { why_kind: "due" }),
        row("c", { why_kind: "later" }),
        row("d", { why_kind: "later", overdue: true }),
        row("b", { why_kind: "due" }),
      ],
    }),
  ).toBe(3);
  expect(toCallNow({ queue: [row("c", { why_kind: "later" })] })).toBe(0);
});
