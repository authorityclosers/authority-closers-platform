import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LeadCard } from "./lead-sheet";
import type { LeadDetail } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  Element.prototype.scrollIntoView = () => undefined;
  // Call facts and the recording terms read the API; nothing answers here.
  vi.stubGlobal("fetch", () => new Promise(() => undefined));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const detail: LeadDetail = {
  lead: {
    lead_id: "11111111-1111-4111-8111-111111111111",
    revision: 3,
    name: "Ravi Kulkarni",
    company: null,
    city: null,
    language: null,
    interest: null,
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

const me = {
  person_id: "22222222-2222-4222-8222-222222222222",
  name: "Seller",
  role: "member",
  can_manage: false,
};

async function show(afterCall: Parameters<typeof LeadCard>[0]["afterCall"]) {
  await act(async () =>
    root.render(
      <LeadCard
        detail={detail}
        me={me}
        onChanged={() => undefined}
        outcome={<section>How did the call go?</section>}
        afterCall={afterCall}
      />,
    ),
  );
}

describe("back from a call, one step at a time (owner's phone test, 19 Oct)", () => {
  it("asks how it went first, with no recording to analyse yet", async () => {
    await show({ step: "outcome" });
    expect(host.textContent).toContain("How did the call go?");
    expect(host.querySelector('[aria-label="Call recording"]')).toBeNull();
  });

  it("then offers the recording alone, and Start calling moves on from there", async () => {
    const onNext = vi.fn();
    await show({ step: "recording", onNext });
    expect(host.textContent).not.toContain("How did the call go?");
    const panel = host.querySelector('[aria-label="Call recording"]');
    expect(panel?.textContent).toContain("Saved. Analyse the call?");
    const skip = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Skip, next lead",
    );
    await act(async () => skip?.click());
    expect(onNext).toHaveBeenCalledOnce();
  });

  it("shows both on a lead opened later, as before", async () => {
    await show(null);
    expect(host.textContent).toContain("How did the call go?");
    expect(
      host.querySelector('[aria-label="Call recording"]')?.textContent,
    ).toContain("Call recording");
  });
});
