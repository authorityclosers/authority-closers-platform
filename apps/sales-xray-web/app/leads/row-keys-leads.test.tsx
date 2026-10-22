// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({ notify: () => undefined }));

import { CallOutcome } from "./lead-sheet";
import type { LeadDetail, LeadRow } from "./leads-client";
import { ListView } from "./list-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Row keys on a computer (Liquid Glass slice 9, 22 Oct 2026): J/K move, Enter
// opens, C asks before calling (as a swipe does), L opens "How did the call go?".
const id = (index: number) =>
  `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;

const row = (index: number, name: string): LeadRow => ({
  lead_id: id(index),
  revision: 1,
  name,
  company: null,
  city: "Pune",
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New lead",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: null,
  why: "New",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-21T05:30:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  // Rows have a size on a real screen; the list counts as shown.
  vi.spyOn(Element.prototype, "getClientRects").mockReturnValue([
    {},
  ] as unknown as DOMRectList);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({
        schema: "lead-desk/1",
        leads: [row(1, "Asha Fictional"), row(2, "Ravi Sample")],
        total: 2,
        next_offset: null,
      }),
    ),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const press = async (key: string) =>
  act(async () => {
    (document.activeElement ?? document.body).dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
    );
  });

it("moves, opens, asks to call and logs from the keyboard", async () => {
  const onOpen = vi.fn();
  const onCall = vi.fn();
  const onLog = vi.fn();
  await act(async () =>
    root.render(
      <ListView
        canManage
        stage="open"
        stageLabel="Open"
        scope="team"
        query=""
        onOpen={onOpen}
        version={0}
        actions={{ onCall, onLog }}
      />,
    ),
  );
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
  await press("j");
  await press("j");
  expect(document.activeElement?.getAttribute("data-row-key")).toBe(id(2));
  await press("k");
  expect(document.activeElement?.getAttribute("data-row-key")).toBe(id(1));
  await press("Enter");
  expect(onOpen).toHaveBeenCalledWith(id(1));
  await press("c");
  expect(onCall).toHaveBeenCalledWith(
    expect.objectContaining({ lead_id: id(1) }),
  );
  await press("l");
  expect(onLog).toHaveBeenCalledWith(
    expect.objectContaining({ lead_id: id(1) }),
  );
});

it("L opens the call's question ready to answer, naming the lead", async () => {
  const detail = {
    lead: row(1, "Asha Fictional"),
    phone: "+919876500001",
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
  } as unknown as LeadDetail;
  await act(async () =>
    root.render(
      <CallOutcome
        detail={detail}
        submitLabel="Save"
        attention={false}
        ask
        beforeSave={async () => detail}
        onSaved={() => undefined}
      />,
    ),
  );
  expect(host.textContent).toContain("How did the call with Asha go?");
  expect(document.activeElement?.textContent).toContain("We talked");
});
