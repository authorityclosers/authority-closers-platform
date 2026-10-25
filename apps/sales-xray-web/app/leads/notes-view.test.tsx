// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ read: vi.fn(), notify: vi.fn() }));

vi.mock("../notice-center", () => ({ notify: calls.notify }));
vi.mock("./leads-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./leads-client")>()),
  readNotes: calls.read,
}));

import type { ActivityPage, LeadEvent } from "./leads-client";
import { NotesView, notesQuery } from "./notes-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = new Date("2026-10-24T12:00:00Z");

const PAGE: ActivityPage = {
  items: [
    {
      event_id: "e2",
      lead_id: "lead-2",
      lead_name: "ravi sample",
      stage_label: "Call back",
      event: {
        kind: "result",
        at: "2026-10-24T11:00:00Z",
        actor_name: "meera fictional",
        note: "Try after 6 pm",
      } as LeadEvent,
    },
    {
      event_id: "e1",
      lead_id: "lead-1",
      lead_name: "asha fictional",
      stage_label: "Interested",
      event: {
        kind: "note",
        at: "2026-10-24T09:00:00Z",
        actor_name: "meera fictional",
        note: "Wants the brochure on WhatsApp",
      } as LeadEvent,
    },
  ],
  next_before: null,
  counts: { note: 2 },
};

let container: HTMLDivElement;
let root: Root;
const opened: [string, string][] = [];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  opened.length = 0;
  calls.read.mockResolvedValue(PAGE);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.clearAllMocks();
});

async function show() {
  await act(async () => {
    root.render(
      <NotesView
        onOpen={(leadId, at) => opened.push([leadId, at])}
        now={() => NOW}
      />,
    );
  });
}

it("lists what was written, newest first, with who wrote it, and opens the lead there", async () => {
  await show();
  expect(calls.read).toHaveBeenCalledWith(null, null, expect.anything());
  const rows = [...container.querySelectorAll("[data-lead-row]")];
  expect(rows.map((row) => row.querySelector("strong")?.textContent)).toEqual([
    "Ravi Sample",
    "Asha Fictional",
  ]);
  expect(rows[0].textContent).toContain("Try after 6 pm");
  expect(rows[0].textContent).toContain("Meera Fictional · Call back");
  await act(async () => (rows[1] as HTMLButtonElement).click());
  expect(opened).toEqual([["lead-1", "2026-10-24T09:00:00Z"]]);
});

it("finds notes by a few words after a short pause, and says when none say them", async () => {
  await show();
  calls.read.mockResolvedValue({ items: [], next_before: null, counts: {} });
  const box = container.querySelector<HTMLInputElement>("input[type=search]");
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    set?.call(box, "brochure");
    box?.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(calls.read).toHaveBeenCalledTimes(1);
  await act(async () => {
    vi.advanceTimersByTime(300);
  });
  expect(calls.read).toHaveBeenLastCalledWith(
    "brochure",
    null,
    expect.anything(),
  );
  expect(container.textContent).toContain("No notes say that");
});

it("looks for two letters at least", () => {
  expect(notesQuery(" a ")).toBe("");
  expect(notesQuery(" 6 pm ")).toBe("6 pm");
});
