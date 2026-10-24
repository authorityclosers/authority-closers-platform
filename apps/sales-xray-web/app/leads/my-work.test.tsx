// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../notice-center", () => ({ notify: () => undefined }));

import type { ActivityPage, LeadEvent } from "./leads-client";
import { MyWork, workWords } from "./my-work";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const event = (kind: LeadEvent["kind"], at: string, extra = {}): LeadEvent =>
  ({
    kind,
    at,
    actor_name: "Meera Fictional",
    ...extra,
  }) as LeadEvent;

const PAGE: ActivityPage = {
  items: [
    {
      event_id: "e3",
      lead_id: "lead-2",
      lead_name: "ravi sample",
      stage_label: "Interested",
      event: event("note", "2026-10-24T09:30:00Z", {
        note: "Wants the brochure on WhatsApp",
      }),
    },
    {
      event_id: "e2",
      lead_id: "lead-1",
      lead_name: "Asha Fictional",
      stage_label: "Meeting / Demo Scheduled",
      event: event("stage", "2026-10-24T08:00:00Z", {
        v: 2,
        stage_label: "Meeting / Demo Scheduled",
        from_label: "Interested",
      }),
    },
  ],
  next_before: null,
  counts: { note: 1, stage: 1, result: 4, call: 3 },
};

let container: HTMLDivElement;
let root: Root;
let asked: string[];

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  asked = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      asked.push(String(input));
      return new Response(JSON.stringify(PAGE), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it("sums up the work in plain words", () => {
  expect(workWords(PAGE.counts)).toBe("4 calls · 1 note · 1 stage move");
  expect(workWords({})).toBe("");
});

it("lists the seller's own work newest first, and opens the lead at that line", async () => {
  const opened = vi.fn();
  await act(async () => root.render(<MyWork onOpen={opened} />));
  expect(asked[0]).toContain("/activity?day=today");
  expect(container.textContent).toContain("4 calls · 1 note · 1 stage move");
  const rows = [...container.querySelectorAll("button[data-lead-row]")];
  expect(rows).toHaveLength(2);
  // Names with capitals; the seller is "You".
  expect(rows[0].textContent).toContain("Ravi Sample");
  expect(rows[0].textContent).toContain("Wants the brochure on WhatsApp");
  expect(container.textContent).not.toContain("Meera");
  await act(async () => (rows[1] as HTMLButtonElement).click());
  expect(opened).toHaveBeenCalledWith("lead-1", "2026-10-24T08:00:00Z");

  // Another day asks the server for that day.
  const week = [...container.querySelectorAll("button")].find(
    (button) => button.textContent === "This week",
  )!;
  await act(async () => week.click());
  expect(asked.at(-1)).toContain("day=week");
});
