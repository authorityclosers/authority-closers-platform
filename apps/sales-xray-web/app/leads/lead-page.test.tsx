import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { StageView } from "./journey/journey-client";
import { lightRow } from "./lead-page-frame";
import { LeadCard } from "./lead-sheet";
import type { LeadDetail } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));

// The lead page's states (P5, spec §5): a closed lead, a viewer, no phone;
// and the row lit for a second back on the list (spec §3).
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  Element.prototype.scrollIntoView = () => undefined;
  vi.stubGlobal("requestAnimationFrame", (run: FrameRequestCallback) =>
    window.setTimeout(() => run(0), 0),
  );
  vi.stubGlobal("fetch", () => new Promise(() => undefined));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const stage = (key: string, label: string, kind: string): StageView =>
  ({
    key,
    label,
    kind,
    kindWords: "",
    milestone: "",
    meaning: "",
    archived: false,
    origin: "stock",
    leads: 0,
  }) as StageView;

const STAGES = [
  stage("new", "New Lead", "new"),
  stage("follow", "Follow-up", "follow_up"),
  stage("keen", "Interested", "interested"),
  stage("won", "Won", "won"),
  stage("lost", "Lost", "lost"),
];

const move = (step: string, label: string, kind: string, group: string) => ({
  step,
  label,
  kind,
  group,
  action: group === "active" ? "move" : "close",
  needs: [],
  asks: [],
  reasons: [],
});

const base: LeadDetail = {
  lead: {
    lead_id: "44444444-4444-4444-8444-444444444444",
    revision: 1,
    name: "Shrikant Fictional Patil",
    company: null,
    city: "Pune",
    language: null,
    interest: "Sales training",
    phone_last4: "3210",
    stage: "follow_up",
    stage_label: "Follow-up",
    source: "manual",
    source_label: "Added by hand",
    owner_person_id: null,
    owner_name: null,
    why: "",
    why_kind: "open",
    next_action_at: null,
    created_at: "2026-11-01T04:00:00Z",
    attempts: 0,
    calls: 0,
    last_result: null,
    last_result_label: null,
    test_data: true,
  },
  phone: "+919876543210",
  email: null,
  owner_reason: null,
  next_action_note: null,
  fields: [],
  source_fields: [],
  events: [],
  can_edit: true,
  can_assign: false,
  reps: [],
  call_mode: "phone",
  moves: [
    move("keen", "Interested", "interested", "active"),
    move("lost", "Lost", "lost", "lost"),
  ],
} as unknown as LeadDetail;

async function show(detail: LeadDetail) {
  await act(async () =>
    root.render(
      <LeadCard
        detail={detail}
        stages={STAGES}
        me={null}
        onChanged={() => undefined}
        outcome={null}
      />,
    ),
  );
}

const buttons = () => [...host.querySelectorAll<HTMLButtonElement>("button")];
const named = (text: string) =>
  [...host.querySelectorAll<HTMLElement>("a, button")].find(
    (item) => item.textContent?.trim() === text,
  );

it("calls an open lead by first name, the stage a strip it can move along", async () => {
  await show(base);
  expect(named("Call Shrikant")).toBeTruthy();
  const strip = host.querySelector('ol[aria-label="Stage"]');
  expect(strip?.querySelector('[aria-current="step"]')?.textContent).toBe(
    "Follow-up",
  );
  // Lost is never a step: it is in More.
  expect(strip?.textContent).not.toContain("Lost");
  expect(
    strip?.querySelector('button[aria-label="Move to Interested"]'),
  ).not.toBeNull();
});

it("shows a closed lead's state as a chip, no follow-up, and Call again", async () => {
  await show({
    ...base,
    lead: { ...base.lead, stage: "won", stage_label: "Won", group: "won" },
  });
  expect(host.querySelector('ol[aria-label="Stage"]')).toBeNull();
  expect(host.textContent).toContain("Won");
  expect(host.textContent).not.toContain("Follow-up ·");
  expect(named("Call again")).toBeTruthy();
});

it("gives a viewer no Note, Follow-up or stage taps, and More only Ask Dipak and Copy link", async () => {
  await show({ ...base, can_edit: false, moves: [] });
  const row = host.querySelector('[data-sx-equal="lead actions"]');
  const words = [...(row?.children ?? [])].map((item) => item.textContent);
  expect(words).toEqual(["WhatsApp", "More"]);
  expect(host.querySelector('ol[aria-label="Stage"] button')).toBeNull();
  const more = buttons().find(
    (button) =>
      button.getAttribute("aria-label") === `More for ${base.lead.name}`,
  )!;
  await act(async () => more.click());
  const sheet = [...document.querySelectorAll("dialog")].find(
    (dialog) => dialog.open,
  );
  expect(
    [...(sheet?.querySelectorAll("li") ?? [])].map((item) =>
      item.textContent?.trim(),
    ),
  ).toEqual(["Ask Dipak about Shrikant", "Copy link"]);
});

it("puts Add a phone number in the Call's place when there is no number", async () => {
  await show({ ...base, phone: null });
  expect(named("Add a phone number")).toBeTruthy();
  expect(named("Call Shrikant")).toBeUndefined();
  const whatsapp = buttons().find((button) =>
    button.textContent?.includes("WhatsApp"),
  );
  expect(whatsapp?.getAttribute("aria-disabled")).toBe("true");
});

it("lights the lead's row for a second back on the list, a positioned row only", () => {
  vi.useFakeTimers();
  const list = document.createElement("ul");
  const row = document.createElement("li");
  row.setAttribute("data-lead-row", "");
  row.style.position = "relative";
  const open = document.createElement("button");
  row.append(open);
  list.append(row);
  document.body.append(list);
  const before = row.classList.length;
  lightRow(open);
  expect(row.classList.length).toBe(before + 1);
  vi.advanceTimersByTime(1000);
  expect(row.classList.length).toBe(before);
  // A tap that focused nothing: the lead's row, found by its key.
  row.setAttribute("data-row-key", "lead-7");
  expect(lightRow(document.body, "lead-7")).toBe(row);
  expect(row.classList.length).toBe(before + 1);
  vi.advanceTimersByTime(1000);
  expect(lightRow(document.body, "another-lead")).toBeNull();
  expect(row.classList.length).toBe(before);
  // A row that isn't positioned would light its whole list: not lit.
  row.style.position = "static";
  lightRow(open);
  expect(row.classList.length).toBe(before);
  list.remove();
});
