// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({ notify: () => undefined }));

import { resetBackCloseForTests } from "../ui/back-close";
import { CallingLoop } from "./lead-sheet";
import type { LeadDetail } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Call mode (approved map, slice 3, 22 Oct 2026): one tap saves and calls the
// next lead; every call still starts from a tap.
const ONE = "11111111-1111-4111-8111-111111111111";
const TWO = "22222222-2222-4222-8222-222222222222";

function detail(leadId: string, name: string, phone: string): LeadDetail {
  return {
    lead: {
      lead_id: leadId,
      revision: 3,
      name,
      company: null,
      city: "Pune",
      language: null,
      interest: null,
      phone_last4: phone.slice(-4),
      stage: "new",
      stage_label: "New",
      source: "manual",
      source_label: "Added by hand",
      owner_person_id: null,
      owner_name: null,
      why: "Call back now",
      why_kind: "due",
      next_action_at: null,
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
  };
}

let host: HTMLDivElement;
let root: Root;
let saved: string[];
let nobodyAfter = false;
const dialled: string[] = [];

beforeEach(() => {
  saved = [];
  nobodyAfter = false;
  dialled.length = 0;
  Element.prototype.scrollIntoView = () => undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith(`/next?skip=${ONE}`))
        return Response.json(
          nobodyAfter ? null : detail(TWO, "Asha Fictional", "+919876500002"),
        );
      if (url.endsWith("/next"))
        return Response.json(detail(ONE, "Ravi Kulkarni", "+919876500001"));
      if (url.endsWith(`/leads/${ONE}/dispose`) && init?.method === "POST") {
        saved.push(ONE);
        return Response.json(detail(ONE, "Ravi Kulkarni", "+919876500001"));
      }
      return Response.json({ detail: "Not Found" }, { status: 404 });
    }),
  );
  // A tap on Call goes to the phone's dialler; here it is only written down.
  const location = window.location;
  vi.spyOn(window, "location", "get").mockReturnValue({
    ...location,
    pathname: "/leads",
    search: "",
    hash: "",
    set href(value: string) {
      dialled.push(value);
    },
    get href() {
      return "http://localhost/leads";
    },
  } as Location);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function flush() {
  await act(async () => {
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
}
const button = (label: string) =>
  [...document.querySelectorAll("button")].find((item) =>
    item.textContent?.trim().startsWith(label),
  );

async function openLoop(onClose = vi.fn()) {
  await act(async () =>
    root.render(
      <CallingLoop
        open
        me={null}
        onClose={onClose}
        onChanged={() => undefined}
      />,
    ),
  );
  await flush();
  return onClose;
}

it("names who is next, and one tap saves and calls them", async () => {
  await openLoop();
  // No answer is one tap now, not two.
  await act(async () => button("No answer")!.click());
  expect(document.body.textContent).toContain("Next: Asha Fictional");
  const save = button("Save and call Asha")!;
  expect(dialled).toEqual([]);
  await act(async () => save.click());
  await flush();
  expect(saved).toEqual([ONE]);
  expect(document.body.textContent).toContain("Asha Fictional");
  expect(dialled).toEqual(["tel:+919876500002"]);
});

it("saves and stops without calling anyone", async () => {
  const onClose = await openLoop();
  await act(async () => button("No answer")!.click());
  await act(async () => button("Save and stop here")!.click());
  await flush();
  expect(saved).toEqual([ONE]);
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(dialled).toEqual([]);
});

it("finishes the round when nobody else is due", async () => {
  nobodyAfter = true;
  await openLoop();
  await act(async () => button("No answer")!.click());
  expect(document.body.textContent).toContain(
    "Nobody else is due after this one.",
  );
  await act(async () => button("Save and finish")!.click());
  await flush();
  expect(saved).toEqual([ONE]);
  expect(document.body.textContent).toContain("That's everyone due right now");
  expect(dialled).toEqual([]);
});

it("keeps the other reasons folded after No answer, and opens them on request", async () => {
  await openLoop();
  await act(async () => button("No answer")!.click());
  expect(document.body.textContent).not.toContain("What happened?");
  await act(async () => button("Didn't get through")!.click());
  expect(document.body.textContent).toContain("What happened?");
  expect(button("Busy")).toBeDefined();
});

// Start calling one pipeline at a time (23 Oct 2026): the loop stays in the
// pipeline To call shows, for the lead now and the one after.
it("reads the next leads from the pipeline To call shows", async () => {
  const asked: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      asked.push(url);
      if (url.endsWith(`/next?skip=${ONE}&pipeline=partner_outreach`))
        return Response.json(null);
      if (url.endsWith("/next?pipeline=partner_outreach"))
        return Response.json(detail(ONE, "Ravi Kulkarni", "+919876500001"));
      return Response.json({ detail: "Not Found" }, { status: 404 });
    }),
  );
  await act(async () =>
    root.render(
      <CallingLoop
        open
        me={null}
        pipeline="partner_outreach"
        onClose={() => undefined}
        onChanged={() => undefined}
      />,
    ),
  );
  await flush();
  expect(
    asked.some((url) => url.endsWith("/next?pipeline=partner_outreach")),
  ).toBe(true);
  expect(
    asked.some((url) =>
      url.endsWith(`/next?skip=${ONE}&pipeline=partner_outreach`),
    ),
  ).toBe(true);
  expect(asked.some((url) => url.endsWith("/next"))).toBe(false);
});
