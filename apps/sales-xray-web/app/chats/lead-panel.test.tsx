import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { LeadDetail } from "../leads/leads-client";
import { LeadPanel } from "./lead-panel";

const LEAD = "11111111-1111-4111-8111-111111111111";
let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string; body?: Record<string, unknown> }[];

const detail = (extra: Partial<LeadDetail> = {}): LeadDetail =>
  ({
    lead: {
      lead_id: LEAD,
      revision: 3,
      name: "Asha Rao",
      company: null,
      city: "Pune",
      language: null,
      interest: null,
      phone_last4: "0001",
      stage: "follow_up",
      stage_label: "Follow-up",
      source: "webhook",
      source_label: "Messenger · Fictional Homes",
      owner_person_id: "p1",
      owner_name: "Neha Joshi",
      why: "Call back",
      why_kind: "due",
      next_action_at: null,
      created_at: "2027-01-15T09:00:00Z",
      attempts: 1,
      calls: 1,
      last_result: null,
      last_result_label: null,
      test_data: false,
    },
    phone: "+919999010001",
    email: null,
    owner_reason: null,
    next_action_note: null,
    fields: [{ label: "City", value: "Pune" }],
    source_fields: [],
    events: [
      {
        kind: "note",
        at: "2027-01-15T09:30:00Z",
        actor_name: "Neha Joshi",
        note: "Wants a ground floor flat.",
      },
    ],
    can_edit: true,
    can_assign: true,
    reps: [
      { person_id: "p1", name: "Neha Joshi", open_leads: 4, available: true },
      { person_id: "p2", name: "Karan Mehta", open_leads: 2, available: true },
    ],
    call_mode: "phone",
    ...extra,
  }) as LeadDetail;

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url.endsWith(`/leads/${LEAD}/notes`))
        return json(
          detail({
            events: [
              {
                kind: "note",
                at: "2027-01-15T10:00:00Z",
                actor_name: "Neha Joshi",
                note: body?.note,
              } as LeadDetail["events"][number],
              ...detail().events,
            ],
          }),
        );
      if (url.endsWith(`/leads/${LEAD}/assign`))
        return json(
          detail({
            lead: {
              ...detail().lead,
              owner_person_id: "p2",
              owner_name: "Karan Mehta",
            },
          }),
        );
      return json(detail());
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const settle = async () => {
  for (let index = 0; index < 5; index += 1)
    await act(async () => {
      await Promise.resolve();
    });
};

it("shows who the lead is, one Call, where they came from and the notes", async () => {
  await act(async () =>
    root.render(<LeadPanel leadId={LEAD} onClose={() => undefined} />),
  );
  await settle();
  expect(host.textContent).toContain("Asha Rao");
  expect(host.textContent).toContain("Follow-up");
  expect(host.textContent).toContain("Messenger · Fictional Homes");
  expect(host.textContent).toContain("Wants a ground floor flat.");
  const call = host.querySelector<HTMLAnchorElement>("a[href$='&call=1']")!;
  expect(call.getAttribute("href")).toBe(`/leads#lead=${LEAD}&call=1`);
  expect(call.textContent).toContain("Call");
});

it("adds a note and moves the lead to another seller", async () => {
  await act(async () =>
    root.render(<LeadPanel leadId={LEAD} onClose={() => undefined} />),
  );
  await settle();
  const box = host.querySelector<HTMLTextAreaElement>("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(box, "Visit on Saturday.");
    box.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const save = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Save note",
  )!;
  await act(async () => save.click());
  await settle();
  expect(calls.find((call) => call.url.endsWith("/notes"))?.body).toMatchObject(
    {
      note: "Visit on Saturday.",
    },
  );
  expect(host.textContent).toContain("Visit on Saturday.");

  const change = [...host.querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Change"),
  )!;
  await act(async () => change.click());
  const find = host.querySelector<HTMLInputElement>(
    "input[aria-label='Find a seller']",
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(find, "kar");
    find.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const picks = [...host.querySelectorAll("ul[aria-label='Sellers'] button")];
  expect(picks.map((pick) => pick.querySelector("span")?.textContent)).toEqual([
    "Karan Mehta",
  ]);
  await act(async () => (picks[0] as HTMLButtonElement).click());
  await settle();
  expect(
    calls.find((call) => call.url.endsWith("/assign"))?.body,
  ).toMatchObject({
    person_id: "p2",
    expected_revision: 3,
  });
  expect(host.textContent).toContain("Karan Mehta");
  expect(host.querySelector("input[aria-label='Find a seller']")).toBeNull();
});
