// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(
  () =>
    [] as Array<{
      title: string;
      action?: { label: string; run: () => void };
    }>,
);
vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({
  notify: (notice: (typeof notices)[number]) => notices.push(notice),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { LeadSheet } from "./lead-sheet";
import type { LeadDetail } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Competitor teardown 10 (2 Nov 2026), the owner's grid kept: the next
// follow-up under the name opens its presets, and a greyed box says why when
// tapped, with what fixes it. Made-up people only.
const ONE = "11111111-1111-4111-8111-111111111111";
const tomorrow = new Date();
tomorrow.setDate(tomorrow.getDate() + 1);
tomorrow.setHours(10, 0, 0, 0);

function detail(next: string | null, phone: string | null): LeadDetail {
  return {
    lead: {
      lead_id: ONE,
      revision: 3,
      name: "Ravi Kulkarni",
      company: null,
      city: "Pune",
      language: null,
      interest: null,
      phone_last4: "3210",
      stage: "follow_up",
      stage_label: "Call back",
      source: "manual",
      source_label: "Added by hand",
      owner_person_id: null,
      owner_name: null,
      why: "Call back",
      why_kind: "due",
      next_action_at: next,
      created_at: "2026-10-18T04:00:00Z",
      attempts: 1,
      calls: 1,
      last_result: null,
      last_result_label: null,
      test_data: true,
    },
    phone,
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
  } as LeadDetail;
}

let shown: LeadDetail;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  notices.length = 0;
  Element.prototype.scrollIntoView = () => undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.endsWith(`/leads/${ONE}`)
        ? Response.json(shown)
        : Response.json({ detail: "Not Found" }, { status: 404 }),
    ),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

async function open(
  next: string | null,
  phone: string | null = "+919876543210",
) {
  shown = detail(next, phone);
  await act(async () =>
    root.render(
      <LeadSheet
        leadId={ONE}
        me={null}
        onClose={() => undefined}
        onChanged={() => undefined}
      />,
    ),
  );
  await act(async () => {
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
}

const button = (start: string) =>
  [...document.querySelectorAll("button")].find((item) =>
    (item.getAttribute("aria-label") ?? item.textContent ?? "").startsWith(
      start,
    ),
  );

it("says the next follow-up under the name, and opens its presets", async () => {
  await open(tomorrow.toISOString());
  const line = [...document.querySelectorAll("button")].find((item) =>
    item.textContent?.startsWith("Follow-up ·"),
  )!;
  expect(line.textContent).toMatch(/^Follow-up · Tomorrow/);
  await act(async () => line.click());
  expect(document.body.textContent).toContain("Remind me");
});

it("says None yet when no follow-up is set", async () => {
  await open(null);
  expect(
    [...document.querySelectorAll("button")].some(
      (item) => item.textContent === "Follow-up · None yet",
    ),
  ).toBe(true);
});

it("greys a box that can't work, and a tap says why with its fix", async () => {
  await open(null, null);
  const whatsapp = button("WhatsApp: add a phone number first")!;
  expect(whatsapp.getAttribute("aria-disabled")).toBe("true");
  expect(whatsapp.disabled).toBe(false);
  await act(async () => whatsapp.click());
  const said = notices.at(-1)!;
  expect(said.title).toBe("WhatsApp: add a phone number first");
  expect(said.action?.label).toBe("Add a number");
  await act(async () => said.action?.run());
  expect(document.body.textContent).toContain("Save details");
  // Email has no address either: its own words and fix.
  await act(async () => button("No email on this lead")!.click());
  expect(notices.at(-1)?.action?.label).toBe("Add an email");
});
