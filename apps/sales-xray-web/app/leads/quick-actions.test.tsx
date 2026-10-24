// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LeadLine, type QuickChannel } from "./desk-view";
import type { LeadRow } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ROW = {
  lead_id: "lead-1",
  revision: 1,
  name: "Asha Fictional",
  company: null,
  city: "Pune",
  language: null,
  interest: "2 BHK",
  phone_last4: "3210",
  stage: "follow_up",
  stage_label: "Call back",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: "me",
  owner_name: "Meera Fictional",
  why: "Call back now",
  why_kind: "due",
  next_action_at: null,
  created_at: "2026-10-24T09:00:00Z",
  attempts: 1,
  calls: 1,
  last_result: null,
  last_result_label: null,
  test_data: false,
} as LeadRow;

let container: HTMLDivElement;
let root: Root;
const tapped: [string, QuickChannel][] = [];
const opened: string[] = [];

function show(row: LeadRow, withTap = true) {
  act(() =>
    root.render(
      <ul>
        <LeadLine
          row={row}
          onOpen={(leadId) => opened.push(leadId)}
          actions={
            withTap
              ? {
                  onTap: (lead, channel) =>
                    tapped.push([lead.lead_id, channel]),
                }
              : {}
          }
        />
      </ul>,
    ),
  );
}

const button = (label: string) =>
  container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  tapped.length = 0;
  opened.length = 0;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

it("calls and opens WhatsApp in one tap, beside the card's own tap area", () => {
  show(ROW);
  act(() => button("Call Asha Fictional")?.click());
  act(() => button("WhatsApp Asha Fictional")?.click());
  expect(tapped).toEqual([
    ["lead-1", "call"],
    ["lead-1", "whatsapp"],
  ]);
  // Neither tap opened the lead by itself; the card still does.
  expect(opened).toEqual([]);
  act(() => button("Open Asha Fictional")?.click());
  expect(opened).toEqual(["lead-1"]);
  // The buttons sit outside the open button: no button inside a button.
  expect(
    container.querySelector("button[aria-label^='Open'] button"),
  ).toBeNull();
});

it("offers Email only when the lead has an address", () => {
  show(ROW);
  expect(button("Email Asha Fictional")).toBeNull();
  show({ ...ROW, has_email: true });
  act(() => button("Email Asha Fictional")?.click());
  expect(tapped).toEqual([["lead-1", "email"]]);
});

it("greys Call and WhatsApp, with why, when there is no number", () => {
  show({ ...ROW, phone_last4: null });
  expect(button("No number to call Asha Fictional")?.disabled).toBe(true);
  expect(button("No number to WhatsApp Asha Fictional")?.disabled).toBe(true);
});

it("keeps the card as it was where a list has no one-tap actions", () => {
  show(ROW, false);
  expect(container.querySelector("[data-quick]")).toBeNull();
  expect(button("Call Asha Fictional")).toBeNull();
  expect(container.textContent).toContain("Call back");
});
