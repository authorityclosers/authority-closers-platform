// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../notice-center", () => ({ notify: vi.fn() }));

import { notify } from "../notice-center";
import type { LeadRow } from "./leads-client";
import { LeadsTable } from "./leads-table";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Editing in the Leads table (owner P0, 23 Oct 2026): click a cell to change
// it; Enter goes down the column, Tab along the row, Escape leaves it.
const id = (index: number) =>
  `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
const SELLER = "00000000-0000-4000-9000-000000000001";
const TEAMMATE = "00000000-0000-4000-9000-000000000002";

const row = (index: number, overrides: Partial<LeadRow> = {}): LeadRow => ({
  lead_id: id(index),
  revision: 1,
  name: "meera fictional",
  company: null,
  city: null,
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New enquiry",
  step: "new_enquiry",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: SELLER,
  owner_name: "swamini fictional",
  why: "New",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-22T06:30:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
  pipeline: "main",
  ...overrides,
});

const STAGES = [
  ["new_enquiry", "New enquiry", "new"],
  ["no_answer", "Couldn't reach", "not_connected"],
  ["keen", "Keen to join", "interested"],
] as const;

let host: HTMLDivElement;
let root: Root;
let sent: { method: string; url: string; body: Record<string, unknown> }[];
let server: Map<string, LeadRow>;
let conflict: boolean;

beforeEach(() => {
  sent = [];
  server = new Map();
  conflict = false;
  vi.mocked(notify).mockClear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : {};
      if (method !== "GET") sent.push({ method, url, body });
      if (url.includes("/journey"))
        return Response.json({
          version: 1,
          stages: [
            ...STAGES.map(([key, label, kind]) => ({
              key,
              label,
              kind,
              archived: false,
            })),
            {
              key: "old",
              label: "Old step",
              kind: "follow_up",
              archived: true,
            },
          ],
        });
      if (url.endsWith("/team"))
        return Response.json({
          reps: [
            { person_id: SELLER, name: "swamini fictional" },
            { person_id: TEAMMATE, name: "asha example" },
          ],
        });
      const match = /\/leads\/([0-9a-f-]+)(?:\/([a-z]+))?$/.exec(url);
      const lead = match ? server.get(match[1]) : undefined;
      if (!match || !lead)
        return Response.json({ detail: "Not Found" }, { status: 404 });
      if (method !== "GET") {
        if (conflict)
          return Response.json(
            { detail: "This lead changed. Check it and try again." },
            { status: 409 },
          );
        const stage = STAGES.find(([key]) => key === body.step);
        const next: LeadRow = {
          ...lead,
          revision: lead.revision + 1,
          ...(typeof body.name === "string" ? { name: body.name } : {}),
          ...(typeof body.phone === "string"
            ? { phone_last4: body.phone.replace(/\D/g, "").slice(-4) }
            : {}),
          ...(stage
            ? { step: stage[0], stage_label: stage[1], stage: stage[2] }
            : {}),
        };
        server.set(lead.lead_id, next);
      }
      return Response.json({
        lead: server.get(match[1]),
        phone: "+91 98765 43210",
        email: null,
      });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const show = async (
  rows: LeadRow[],
  rights: { canManage: boolean; onSaved?: () => void },
  extra: { showOwner?: boolean; several?: boolean } = {},
) => {
  for (const item of rows) server.set(item.lead_id, item);
  await act(async () =>
    root.render(
      <LeadsTable
        rows={rows}
        onOpen={() => undefined}
        showOwner={extra.showOwner ?? false}
        pipelineNames={
          extra.several
            ? new Map([
                ["main", "Enrolment"],
                ["partner_outreach", "Partner outreach"],
              ])
            : null
        }
        edit={{
          canManage: rights.canManage,
          me: SELLER,
          onSaved: rights.onSaved ?? (() => undefined),
        }}
      />,
    ),
  );
};

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
const click = async (element: Element | null) => {
  expect(element).not.toBeNull();
  await act(async () => (element as HTMLElement).click());
  await settle();
};
const cell = (leadId: string, column: string) =>
  host.querySelector<HTMLElement>(`[data-cell="${leadId}:${column}"]`);
const editor = () =>
  host.querySelector<HTMLInputElement & HTMLSelectElement>(
    "td[data-editing] input, td[data-editing] select",
  );
const type = async (input: HTMLInputElement, value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
const choose = async (select: HTMLSelectElement, value: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLSelectElement.prototype,
      "value",
    )!.set!.call(select, value);
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
};
const press = async (element: Element, key: string, shiftKey = false) => {
  await act(async () => {
    element.dispatchEvent(
      new KeyboardEvent("keydown", {
        key,
        shiftKey,
        bubbles: true,
        cancelable: true,
      }),
    );
  });
  await settle();
};
const button = (label: string) =>
  host.querySelector(`button[aria-label="${label}"]`);

it("picks a stage in place, from the pipeline's own stages, with the lead's revision", async () => {
  await show([row(1)], { canManage: false });
  await click(cell(id(1), "stage"));
  const pick = editor()!;
  expect(pick.tagName).toBe("SELECT");
  expect(pick.getAttribute("aria-label")).toBe("Stage of Meera Fictional");
  // Archived stages and the one a call sets (nobody picked up) aren't offered.
  expect(Array.from(pick.options, (option) => option.text)).toEqual([
    "New enquiry",
    "Keen to join",
  ]);
  await choose(pick, "keen");
  expect(sent).toHaveLength(1);
  expect(sent[0].url).toMatch(new RegExp(`/leads/${id(1)}/stage$`));
  expect(sent[0].body).toMatchObject({ expectedRevision: 1, step: "keen" });
  expect(editor()).toBeNull();
  expect(cell(id(1), "stage")?.textContent).toContain("Keen to join");
  expect(document.activeElement).toBe(cell(id(1), "stage"));
});

it("renames with Enter and goes down the column; Escape leaves the next as it was", async () => {
  await show(
    [row(1), row(2, { name: "ravi sample", owner_person_id: TEAMMATE })],
    { canManage: true },
  );
  await click(button("Rename Meera Fictional"));
  const first = editor()!;
  expect(first.value).toBe("meera fictional");
  expect(document.activeElement).toBe(first);
  await type(first, "Meera Joshi");
  await press(first, "Enter");
  expect(sent).toHaveLength(1);
  expect(sent[0]).toMatchObject({
    method: "PATCH",
    body: { expected_revision: 1, name: "Meera Joshi" },
  });
  const second = editor()!;
  expect(second.getAttribute("aria-label")).toBe("Name of Ravi Sample");
  expect(document.activeElement).toBe(second);
  await type(second, "ravi something");
  await press(second, "Escape");
  expect(sent).toHaveLength(1);
  expect(editor()).toBeNull();
  expect(host.querySelector("tbody")?.textContent).toContain("Meera Joshi");
  expect(host.querySelector("tbody")?.textContent).toContain("Ravi Sample");
});

it("goes along the row with Tab, with the lead's whole number to correct", async () => {
  await show([row(1)], { canManage: false });
  await click(button("Rename Meera Fictional"));
  await press(editor()!, "Tab");
  const phone = editor()!;
  expect(phone.getAttribute("aria-label")).toBe("Phone of Meera Fictional");
  expect(phone.value).toBe("+91 98765 43210");
  await type(phone, "+91 98765 00000");
  await press(phone, "Tab");
  expect(sent).toHaveLength(1);
  expect(sent[0]).toMatchObject({
    method: "PATCH",
    body: { expected_revision: 1, phone: "+91 98765 00000" },
  });
  expect(editor()?.getAttribute("aria-label")).toBe("Stage of Meera Fictional");
  // Shift+Tab goes back; nothing typed, nothing saved.
  await press(editor()!, "Tab", true);
  expect(editor()?.getAttribute("aria-label")).toBe("Phone of Meera Fictional");
  await press(editor()!, "Escape");
  expect(sent).toHaveLength(1);
  expect(host.querySelector("tbody")?.textContent).toContain("•• 0000");
});

it("lets a seller change only their own leads, and only owners and admins the owner and pipeline", async () => {
  const leads = [
    row(1),
    row(2, { name: "ravi sample", owner_person_id: TEAMMATE }),
  ];
  await show(leads, { canManage: false }, { showOwner: true, several: true });
  expect(cell(id(1), "stage")).not.toBeNull();
  expect(cell(id(1), "phone")).not.toBeNull();
  expect(button("Rename Meera Fictional")).not.toBeNull();
  expect(cell(id(1), "owner")).toBeNull();
  expect(cell(id(1), "pipeline")).toBeNull();
  expect(cell(id(2), "stage")).toBeNull();
  expect(button("Rename Ravi Sample")).toBeNull();

  await show(leads, { canManage: true }, { showOwner: true, several: true });
  expect(cell(id(2), "stage")).not.toBeNull();
  await click(cell(id(2), "owner"));
  const owner = editor()!;
  expect(Array.from(owner.options, (option) => option.text)).toEqual([
    "No owner",
    "Asha Example",
    "Swamini Fictional",
  ]);
  await choose(owner, SELLER);
  expect(sent[0].url).toMatch(new RegExp(`/leads/${id(2)}/assign$`));
  expect(sent[0].body).toMatchObject({
    expected_revision: 1,
    person_id: SELLER,
  });
  await click(cell(id(1), "pipeline"));
  expect(Array.from(editor()!.options, (option) => option.text)).toEqual([
    "Enrolment",
    "Partner outreach",
  ]);
});

it("waits for a lead's last save before the next, and says when someone else changed it", async () => {
  const onSaved = vi.fn();
  await show([row(1)], { canManage: true, onSaved });
  await click(button("Rename Meera Fictional"));
  await type(editor()!, "Meera Joshi");
  await press(editor()!, "Tab");
  await press(editor()!, "Tab");
  await choose(editor()!, "keen");
  expect(
    sent.map((item) => [
      item.method,
      item.body.expected_revision ?? item.body.expectedRevision,
    ]),
  ).toEqual([
    ["PATCH", 1],
    ["POST", 2],
  ]);
  expect(cell(id(1), "stage")?.textContent).toContain("Keen to join");

  conflict = true;
  await click(cell(id(1), "stage"));
  await choose(editor()!, "new_enquiry");
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "error", title: "This lead changed" }),
  );
  expect(onSaved).toHaveBeenCalled();
  // What was picked goes back to what the server last said.
  expect(cell(id(1), "stage")?.textContent).toContain("Keen to join");
});
