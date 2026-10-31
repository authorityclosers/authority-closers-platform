import { expect, it } from "vitest";

import { nextLine } from "./desk-view";
import type { LeadRow } from "./leads-client";
import { pageWords, shortSource, sourceKind } from "./source-mark";

// Rows (owner, 31 Oct 2026): "Stage · Source" with a short source and its mark;
// the next action without the stage again.
const from = (source: string, source_label: string) => ({
  source,
  source_label,
});

it("names a website page in words, abbreviations in capitals", () => {
  expect(pageWords("/courses/soc-analyst")).toBe("SOC Analyst");
  expect(pageWords("https://example.test/courses/ceh-training.html?x=1")).toBe(
    "CEH Training",
  );
  expect(pageWords("/")).toBe("");
  expect(shortSource(from("webhook", "Website: /courses/soc-analyst"))).toBe(
    "Website · SOC Analyst",
  );
  expect(shortSource(from("webhook", "Website: /"))).toBe("Website");
  expect(shortSource(from("webhook", "Website form"))).toBe("Website");
});

it("gives each source its kind and a short name", () => {
  expect(sourceKind(from("meta", "Spring course form"))).toBe("meta");
  expect(shortSource(from("meta", "Spring course form"))).toBe("Meta Ads");
  expect(sourceKind(from("webhook", "Google Ads lead form"))).toBe("google");
  expect(shortSource(from("webhook", "Google Ads lead form"))).toBe(
    "Google Ads",
  );
  expect(sourceKind(from("sheet", "Sheet: October fair"))).toBe("sheet");
  expect(shortSource(from("sheet", "Sheet: October fair"))).toBe(
    "Sheet · October fair",
  );
  expect(sourceKind(from("csv", "File: leads.csv"))).toBe("file");
  expect(shortSource(from("csv", "File: leads.csv"))).toBe("File upload");
  expect(sourceKind(from("manual", "Added by hand"))).toBe("manual");
  expect(sourceKind(from("partner_api", "Partner"))).toBe("other");
});

it("says when a new lead was added instead of naming its stage again", () => {
  const now = new Date(2026, 9, 31, 12, 0);
  const row = {
    why: "New lead",
    why_kind: "new",
    created_at: new Date(2026, 9, 29, 12, 0).toISOString(),
    next_action_at: null,
    missed_at: null,
  } as unknown as LeadRow;
  expect(nextLine(row, now)).toBe("Added 2 days ago");
  const later = {
    ...row,
    why: "Call back",
    why_kind: "later",
    next_action_at: new Date(2026, 9, 31, 16, 0).toISOString(),
  } as LeadRow;
  expect(nextLine(later, now)).toMatch(/^Call back · /);
});

it("keeps a late row's time short, so it is never cut (persona QA, 31 Oct 2026)", () => {
  const now = new Date(2026, 9, 31, 12, 0);
  const late = {
    why: "Call back",
    why_kind: "due",
    created_at: new Date(2026, 9, 20, 12, 0).toISOString(),
    next_action_at: new Date(2026, 9, 30, 17, 30).toISOString(),
    missed_at: null,
  } as unknown as LeadRow;
  expect(nextLine(late, now)).toMatch(/^Call back · /);
  expect(nextLine(late, now)).not.toContain("was");
});

it("never names the stage again, and says nothing more for a closed lead (phone personas, 1 Nov 2026: Won Won)", () => {
  const now = new Date(2026, 9, 31, 12, 0);
  const row = {
    stage_label: "Open Leads",
    why: "Open Leads",
    why_kind: "open",
    created_at: new Date(2026, 9, 20, 12, 0).toISOString(),
    next_action_at: new Date(2026, 10, 2, 8, 0).toISOString(),
    missed_at: null,
  } as unknown as LeadRow;
  expect(nextLine(row, now)).toMatch(/^Next call · /);
  expect(nextLine({ ...row, next_action_at: null }, now)).toBe(
    "No next call yet",
  );
  const due = {
    ...row,
    stage_label: "Meeting Done",
    why: "Meeting Done due",
    why_kind: "due",
    next_action_at: new Date(2026, 9, 31, 8, 10).toISOString(),
  } as LeadRow;
  expect(nextLine(due, now)).toMatch(/^Due · /);
  expect(nextLine(due, now)).not.toContain("Meeting Done");
  const won = {
    ...row,
    stage_label: "Won",
    why: "Won",
    why_kind: "closed",
    next_action_at: null,
  } as LeadRow;
  expect(nextLine(won, now)).toBe("");
});
