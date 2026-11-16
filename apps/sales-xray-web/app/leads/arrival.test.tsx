// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: unknown; href: string }) => (
    <a href={href}>{children as never}</a>
  ),
}));

import {
  arrivedShort,
  forgetSeen,
  isNewSince,
  SEEN_KEY,
  timelineWords,
} from "./arrival";
import { dayInput, rangeOf, rangeWords } from "./arrived-pick";
import { LeadLine } from "./desk-view";
import { LeadTimeline } from "./lead-sheet";
import type { LeadRow } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 16 Nov 2026 (a client's admin asked "when did this lead actually
// generate?"): every row says when its lead came in, the lead page has a
// Timeline, and a new Meta lead nobody owns reads as one status line.
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  window.localStorage.clear();
  forgetSeen();
});

const NOW = new Date(2026, 10, 16, 15, 0);
const before = (minutes: number) =>
  new Date(NOW.getTime() - minutes * 60_000).toISOString();

const row = {
  lead_id: "11111111-1111-4111-8111-111111111111",
  revision: 1,
  name: "Fictional Shreya",
  company: null,
  city: "Pune",
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New",
  source: "meta",
  source_label: "Meta ad",
  owner_person_id: null,
  owner_name: null,
  why: "Waiting for an owner",
  why_kind: "waiting",
  next_action_at: null,
  created_at: "2026-11-16T09:00:00Z",
  received_at: "2026-11-16T08:00:00Z",
  updated_at: "2026-11-16T09:30:00Z",
  assigned_at: null,
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: true,
  side: "inbound",
} as unknown as LeadRow;

it("says when a lead came in, short", () => {
  expect(arrivedShort(before(0), NOW)).toBe("now");
  expect(arrivedShort(before(12), NOW)).toBe("12 min");
  expect(arrivedShort(before(130), NOW)).toBe("2 h");
  expect(arrivedShort(new Date(2026, 10, 15, 22, 0).toISOString(), NOW)).toBe(
    "Yesterday",
  );
  expect(arrivedShort(new Date(2026, 10, 13, 9, 0).toISOString(), NOW)).toBe(
    "3 d",
  );
  expect(arrivedShort(new Date(2026, 9, 12, 9, 0).toISOString(), NOW)).toBe(
    "12 Oct",
  );
  expect(arrivedShort(new Date(2025, 9, 12, 9, 0).toISOString(), NOW)).toBe(
    "12 Oct 2025",
  );
  expect(timelineWords(before(130), NOW)).toMatch(/16 Nov 2026.* · 2 h ago$/);
});

it("marks a lead New only when it came in after the last visit", () => {
  const seen = Date.parse("2026-11-16T08:30:00Z");
  expect(isNewSince(row, null)).toBe(false);
  // Its source's time counts, not when it was brought in.
  expect(isNewSince(row, seen)).toBe(false);
  expect(isNewSince({ ...row, received_at: null }, seen)).toBe(true);
});

it("reads an unowned new Meta lead as one status line, with its time", async () => {
  // The last visit, before this lead came in.
  window.localStorage.setItem(
    SEEN_KEY,
    String(Date.parse("2026-11-16T07:00:00Z")),
  );
  forgetSeen();
  await act(async () =>
    root.render(
      <ul>
        <LeadLine
          row={row}
          onOpen={() => undefined}
          compact
          showOwner
          stageWord="New"
        />
      </ul>,
    ),
  );
  expect(host.querySelector('[class*="leadSub"]')?.textContent).toMatch(
    /^New · Meta.* · No owner$/,
  );
  expect(host.textContent).not.toContain("No owner yet");
  expect(host.textContent).not.toContain("Waiting for an owner");
  expect(host.querySelector("[data-lead-new]")?.textContent).toBe("New");
  expect(host.querySelector("[data-lead-age]")?.getAttribute("title")).toMatch(
    /^Came in 16 Nov 2026/,
  );
});

it("shows a seller only Received, and a manager the whole Timeline", async () => {
  await act(async () =>
    root.render(<LeadTimeline lead={row} full={false} now={NOW} />),
  );
  const keys = () =>
    [...host.querySelectorAll("[data-timeline]")].map((item) =>
      item.getAttribute("data-timeline"),
    );
  expect(keys()).toEqual(["received"]);
  expect(host.querySelector("time")?.getAttribute("datetime")).toBe(
    row.received_at,
  );
  await act(async () =>
    root.render(<LeadTimeline lead={row} full now={NOW} />),
  );
  expect(keys()).toEqual(["received", "added", "updated", "assigned"]);
  expect(host.textContent).toContain("Added to Sales X-Ray");
  expect(host.textContent).toContain("Not assigned yet");
});

it("turns the date choice into the days Leads per day reads", () => {
  expect(rangeOf({ created: "yesterday" }, NOW)).toEqual({
    since: "2026-11-15",
    until: "2026-11-15",
  });
  expect(rangeOf({}, NOW)).toEqual({
    since: dayInput(29, NOW),
    until: "2026-11-16",
  });
  expect(rangeOf({ since: "2026-11-01", until: "2026-11-09" }, NOW)).toEqual({
    since: "2026-11-01",
    until: "2026-11-09",
  });
  expect(rangeWords("2026-11-01", "2026-11-09")).toBe("1 Nov – 9 Nov");
});
