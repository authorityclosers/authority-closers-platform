// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({ notify: () => undefined }));

import { resetBackCloseForTests } from "../ui/back-close";
import { CallNext } from "./call-next";
import { LeadSheet } from "./lead-sheet";
import type { LeadDetail, LeadEvent } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ONE = "11111111-1111-4111-8111-111111111111";
const TWO = "22222222-2222-4222-8222-222222222222";
// The open lead's history (a call the phone logged, for the after-call tests).
let history: LeadEvent[] = [];

function detail(leadId: string, name: string): LeadDetail {
  return {
    lead: {
      lead_id: leadId,
      revision: 3,
      name,
      company: null,
      city: "Pune",
      language: null,
      interest: null,
      phone_last4: "3210",
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
    phone: "+919876543210",
    email: null,
    owner_reason: null,
    next_action_note: null,
    fields: [],
    source_fields: [],
    events: leadId === ONE ? history : [],
    can_edit: true,
    can_assign: false,
    reps: [],
    call_mode: "phone",
  };
}

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  history = [];
  Element.prototype.scrollIntoView = () => undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith(`/leads/${ONE}`) && !init?.method)
        return Response.json(detail(ONE, "Ravi Kulkarni"));
      if (url.endsWith(`/leads/${ONE}/dispose`))
        return Response.json(detail(ONE, "Ravi Kulkarni"));
      if (url.includes(`/next?skip=${ONE}`))
        return Response.json(detail(TWO, "Asha Fictional"));
      return Response.json({ detail: "Not Found" }, { status: 404 });
    }),
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

async function flush() {
  await act(async () => {
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
}
const tile = (label: string) =>
  [...document.querySelectorAll("button")].find((button) =>
    button.textContent?.startsWith(label),
  )!;

// Dipak's Home + Leads handoff (31 Oct 2026, items 16-17): a one-off call
// saves and closes; from Call Next, Save & Next Lead goes on through the list.
it.each([
  [false, "Save & Close"],
  [true, "Save & Next Lead"],
])("after a call opened with queue %s, saves with %s", async (queue, label) => {
  const onNext = vi.fn();
  const onClose = vi.fn();
  await act(async () =>
    root.render(
      <LeadSheet
        leadId={ONE}
        me={null}
        onClose={onClose}
        onChanged={() => undefined}
        onNext={onNext}
        queue={queue}
      />,
    ),
  );
  await flush();
  // No call yet: the question waits behind its light chip.
  await act(async () => tile("Log a call").click());
  await act(async () => tile("Didn't get through").click());
  await act(async () => tile("No answer").click());
  await act(async () => tile(label).click());
  await flush();
  if (queue) {
    expect(onNext).toHaveBeenCalledWith(ONE);
    expect(onClose).not.toHaveBeenCalled();
  } else {
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onNext).not.toHaveBeenCalled();
  }
  expect(document.querySelector('[class*="nextUp"]')).toBeNull();
});

// One shared "Call next" (Liquid Glass split, 22 Oct 2026): the same card wherever it sits.
it("says plainly when nobody else is due", async () => {
  await act(async () =>
    root.render(<CallNext lead={null} saved onCall={() => undefined} />),
  );
  expect(host.textContent).toBe("Saved. Nobody else is due now.");
  await act(async () =>
    root.render(
      <CallNext
        lead={detail(TWO, "Asha Fictional")}
        onCall={() => undefined}
      />,
    ),
  );
  expect(host.textContent).toContain("Next up: Asha Fictional");
  expect(host.textContent).not.toContain("Saved.");
});

// "How did it go?" only after a real call (owner, 23 Oct 2026).
it("keeps the question behind a light chip until a real call", async () => {
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
  await flush();
  expect(host.textContent).not.toContain("How did the call");
  expect(document.body.textContent).not.toContain("How did the call");
  await act(async () => tile("Log a call").click());
  expect(document.body.textContent).toContain("How did the call with Ravi go?");
});

it("asks straight away after a call the phone logged with talk time", async () => {
  history = [
    {
      kind: "call",
      at: new Date(Date.now() - 3 * 60_000).toISOString(),
      actor_name: null,
      stage: null,
      stage_label: null,
      reason: null,
      reason_label: null,
      connected: true,
      note: null,
      next_action_at: null,
      owner_name: null,
      previous_owner_name: null,
      allocation_reason: null,
      source_label: null,
      submission_id: null,
      simulated: null,
      duration_seconds: 82,
      via: "phone",
      direction: "outgoing",
    },
  ];
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
  await flush();
  const text = document.body.textContent ?? "";
  expect(text).toContain("Back from the call with Ravi. How did it go?");
  expect(text).toContain(
    "Your phone says you talked for 1\u00a0min 22\u00a0s.",
  );
  expect(tile("Log a call")).toBeUndefined();
});

// ph2-13 (phone personas, 1 Nov 2026): a round opens the lead's card first,
// with Call and Skip; Skip goes on to the next lead and saves nothing.
it.each([true, false])(
  "offers Skip beside Call only in a round (%s)",
  async (queue) => {
    const onNext = vi.fn();
    const fetchMock = vi.mocked(fetch);
    await act(async () =>
      root.render(
        <LeadSheet
          leadId={ONE}
          me={null}
          onClose={() => undefined}
          onChanged={() => undefined}
          onNext={onNext}
          queue={queue}
        />,
      ),
    );
    await flush();
    const skip = [...document.querySelectorAll("button")].find(
      (button) => button.textContent === "Skip",
    );
    if (!queue) {
      expect(skip).toBeUndefined();
      return;
    }
    const calls = fetchMock.mock.calls.length;
    await act(async () => skip!.click());
    // Skip sends the lead to the round's end (competitor teardown 2).
    expect(onNext).toHaveBeenCalledWith(ONE, true);
    // Nothing saved: no request beyond the lead's own read.
    expect(
      fetchMock.mock.calls
        .slice(calls)
        .filter(
          ([, init]) => (init as RequestInit | undefined)?.method === "POST",
        ),
    ).toHaveLength(0);
  },
);

// QA robot bbc3aca3 (1 Nov 2026): "is your lead now" opened a lead that had
// moved on, and the sheet offered a Try again that could never work.
it("says a lead that moved off your desk has, with Close and no Try again", async () => {
  const onClose = vi.fn();
  await act(async () =>
    root.render(
      <LeadSheet
        leadId="33333333-3333-4333-8333-333333333333"
        me={null}
        onClose={onClose}
        onChanged={() => undefined}
      />,
    ),
  );
  await flush();
  expect(document.body.textContent).toContain(
    "This lead isn't on your desk any more",
  );
  expect(tile("Try again")).toBeUndefined();
  await act(async () => tile("Close").click());
  expect(onClose).toHaveBeenCalledTimes(1);
});
