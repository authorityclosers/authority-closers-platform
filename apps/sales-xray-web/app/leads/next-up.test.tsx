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
import type { LeadDetail } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ONE = "11111111-1111-4111-8111-111111111111";
const TWO = "22222222-2222-4222-8222-222222222222";

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
    events: [],
    can_edit: true,
    can_assign: false,
    reps: [],
    call_mode: "phone",
  };
}

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
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

// The ease-of-use wave, 22 Oct 2026: "Call next" after any saved outcome.
it("says who is next after a save, and calls them in one tap", async () => {
  const onNext = vi.fn();
  await act(async () =>
    root.render(
      <LeadSheet
        leadId={ONE}
        me={null}
        onClose={() => undefined}
        onChanged={() => undefined}
        onNext={onNext}
      />,
    ),
  );
  await flush();
  await act(async () => tile("Didn't get through").click());
  await act(async () => tile("No answer").click());
  await act(async () => tile("Save").click());
  await flush();
  const bar = document.querySelector('[role="status"][class*="nextUp"]');
  expect(bar?.textContent).toContain("Saved. Next up: Asha Fictional");
  await act(async () => tile("Call Asha").click());
  expect(onNext).toHaveBeenCalledWith(TWO);
});

// One shared "Call next" (Liquid Glass split, 22 Oct 2026): the same card wherever it sits.
it("says plainly when nobody else is due", async () => {
  await act(async () =>
    root.render(<CallNext lead={null} saved onCall={() => undefined} />),
  );
  expect(host.textContent).toBe("Saved. Nobody else is due now.");
  await act(async () =>
    root.render(
      <CallNext lead={detail(TWO, "Asha Fictional")} onCall={() => undefined} />,
    ),
  );
  expect(host.textContent).toContain("Next up: Asha Fictional");
  expect(host.textContent).not.toContain("Saved.");
});
