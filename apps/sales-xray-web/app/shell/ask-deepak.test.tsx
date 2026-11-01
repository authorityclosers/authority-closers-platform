// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  read: vi.fn(),
  search: vi.fn(),
  report: vi.fn(),
}));

vi.mock("../leads/leads-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../leads/leads-client")>()),
  readLead: calls.read,
  searchDesk: calls.search,
}));
vi.mock("../acquisition-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../acquisition-client")>()),
  acquisition: calls.report,
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { AskDipakSheet } from "./ask-deepak";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Phone personas ph1-35 (1 Nov 2026): the tab bar's Ask Dipak said "coming
// soon". It now answers from a lead's own last call and notes. Fictional data.
const CALL = "4b8f3c1e-2a9d-4e6f-8b1c-0d2e3f4a5b6c";

const detail = (events: object[], extra: object = {}) => ({
  lead: {
    lead_id: "lead-1",
    name: "asha fictional",
    stage_label: "Interested",
    next_action_at: null,
  },
  next_action_note: null,
  events,
  ...extra,
});

const event = (kind: string, extra: object = {}) => ({
  kind,
  at: "2026-10-30T06:00:00+00:00",
  actor_name: "ravi fictional",
  note: null,
  submission_id: null,
  ...extra,
});

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  calls.report.mockResolvedValue({
    report: {
      content: {
        pillars: {
          summary: "They want a site visit before deciding.",
          biggest_concern: { short: "The price is above their budget" },
          next_step: { text: "Send the floor plan" },
        },
      },
    },
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.clearAllMocks();
});

const page = () => document.body.textContent ?? "";

async function settle(ms = 0) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

it("answers about the lead it opened from: its last call and its notes", async () => {
  calls.read.mockResolvedValue(
    detail(
      [
        event("note", { note: "Wife decides; call after 6" }),
        event("call", { submission_id: CALL }),
        event("result", { note: "Asked for the brochure" }),
        event("stage"),
      ],
      // The follow-up was saved with the newest note: its words show once.
      {
        next_action_note: "Wife decides; call after 6",
        lead: {
          lead_id: "lead-1",
          name: "asha fictional",
          stage_label: "Interested",
          next_action_at: "2026-11-03T05:30:00+00:00",
        },
      },
    ),
  );
  await act(async () =>
    root.render(
      <AskDipakSheet
        open
        leadId="lead-1"
        about="asha fictional"
        onClose={() => {}}
      />,
    ),
  );
  await settle();
  expect(calls.read).toHaveBeenCalledWith("lead-1", expect.anything());
  expect(page()).toContain("Ask Dipak about Asha Fictional");
  expect(page()).toContain("What happened");
  expect(page()).toContain("They want a site visit before deciding.");
  expect(page()).toContain("What holds them back");
  expect(page()).toContain("The price is above their budget");
  expect(page()).toContain("Send the floor plan");
  expect(page()).toContain("Wife decides; call after 6");
  expect(page().split("Wife decides; call after 6")).toHaveLength(2);
  expect(page()).toContain("Follow-up");
  expect(page()).toContain("Asked for the brochure");
  expect(page()).toContain("Ravi Fictional");
  expect(page()).not.toMatch(/soon/i);
  expect(calls.search).not.toHaveBeenCalled();
  const report = document.querySelector<HTMLAnchorElement>(
    'a[href*="4b8f3c1e"]',
  );
  expect(report?.textContent).toBe("Open the report");
});

it("says plainly when nothing is known yet, and invents nothing", async () => {
  calls.read.mockResolvedValue(detail([event("stage")]));
  await act(async () =>
    root.render(
      <AskDipakSheet
        open
        leadId="lead-1"
        about="asha fictional"
        onClose={() => {}}
      />,
    ),
  );
  await settle();
  expect(page()).toContain("Nothing on Asha Fictional yet");
  expect(page()).not.toContain("What happened");
  expect(calls.report).not.toHaveBeenCalled();
});

it("opened from a lead without its id, it has already searched its name", async () => {
  calls.search.mockResolvedValue({
    leads: [
      { lead_id: "lead-1", name: "asha fictional", stage_label: "Interested" },
    ],
    notes: [],
    tasks: [],
  });
  await act(async () =>
    root.render(
      <AskDipakSheet open about="asha fictional" onClose={() => {}} />,
    ),
  );
  await settle(300);
  expect(calls.search).toHaveBeenCalledWith(
    "asha fictional",
    expect.anything(),
  );
  expect(page()).toContain("Ask Dipak about Asha Fictional");
  expect(page()).toContain("Interested");
});

it("from the tab bar, finds the lead by name first, and goes back to another", async () => {
  calls.search.mockResolvedValue({
    leads: [
      { lead_id: "lead-1", name: "asha fictional", stage_label: "Interested" },
    ],
    notes: [],
    tasks: [],
  });
  calls.read.mockResolvedValue(
    detail([event("note", { note: "Wife decides; call after 6" })], {
      next_action_note: "Share the price list",
      lead: {
        lead_id: "lead-1",
        name: "asha fictional",
        stage_label: "Interested",
        next_action_at: "2026-11-03T05:30:00+00:00",
      },
    }),
  );
  await act(async () => root.render(<AskDipakSheet open onClose={() => {}} />));
  expect(page()).toContain("Before a call, see what the last call");
  expect(calls.read).not.toHaveBeenCalled();
  const input = document.querySelector<HTMLInputElement>(
    'input[type="search"]',
  )!;
  const setValue = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  await act(async () => {
    setValue.call(input, "as");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(300);
  expect(calls.search).toHaveBeenCalledWith("as", expect.anything());
  const pick = [...document.querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Asha Fictional"),
  )!;
  await act(async () => pick.click());
  await settle();
  expect(page()).toContain("Wife decides; call after 6");
  expect(page()).toContain("Share the price list");
  expect(page()).toContain("Follow-up");
  const other = [...document.querySelectorAll("button")].find(
    (button) => button.textContent === "Another lead",
  )!;
  await act(async () => other.click());
  expect(document.querySelector('input[type="search"]')).not.toBeNull();
});
