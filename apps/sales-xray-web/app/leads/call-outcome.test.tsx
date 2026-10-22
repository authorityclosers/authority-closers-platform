import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CallOutcome, stageAfterTalk } from "./lead-sheet";
import type { LeadDetail, Stage } from "./leads-client";
import { missedReason, type NativeCall } from "./native-phone";

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
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

function lead(stage: Stage): LeadDetail {
  return {
    lead: {
      lead_id: "11111111-1111-4111-8111-111111111111",
      revision: 3,
      name: "Ravi Kulkarni",
      company: null,
      city: null,
      language: null,
      interest: null,
      phone_last4: "3210",
      stage,
      stage_label: stage,
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
}

const heard = (result: NativeCall["result"]): NativeCall => ({
  leadId: "11111111-1111-4111-8111-111111111111",
  number: "+919876543210",
  startedMs: 1,
  endedMs: 9000,
  durationSeconds: 0,
  connected: false,
  result,
  recording: null,
  final: true,
});

const tile = (label: string) =>
  [...host.querySelectorAll("button")].find((button) =>
    button.textContent?.startsWith(label),
  )!;

async function show(detail: LeadDetail, call: NativeCall | null = null) {
  await act(async () =>
    root.render(
      <CallOutcome
        detail={detail}
        submitLabel="Save"
        attention={false}
        heard={call}
        beforeSave={async () => detail}
        onSaved={() => undefined}
      />,
    ),
  );
}

describe("the after-call sheet (UX study item 6)", () => {
  it("chooses the lead's stage again after We talked", async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () => new Response(JSON.stringify(lead("interested"))),
    );
    vi.stubGlobal("fetch", fetchMock);
    await show(lead("interested"));
    await act(async () => tile("We talked").click());
    expect(tile("Interested").getAttribute("aria-pressed")).toBe("true");
    // Didn't get through, then back: the stage comes back too.
    await act(async () => tile("Didn").click());
    await act(async () => tile("We talked").click());
    expect(tile("Interested").getAttribute("aria-pressed")).toBe("true");
    await act(async () => tile("Save").click());
    const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(body).toMatchObject({ connected: true, stage: "interested" });
  });

  it("leaves the stage open for a new lead", async () => {
    await show(lead("new"));
    await act(async () => tile("We talked").click());
    expect(
      host.querySelectorAll(
        '[aria-label="What happens next"] [aria-pressed="true"]',
      ),
    ).toHaveLength(0);
  });

  // Owner, 22 Oct 2026: Save looked dead after We talked, and nothing said why.
  it("says what Save still needs, and saves nothing until it is picked", async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () => new Response(JSON.stringify(lead("new"))),
    );
    vi.stubGlobal("fetch", fetchMock);
    await show(lead("new"));
    await act(async () => tile("We talked").click());
    const hint = () => host.querySelector('p[role="status"]');
    expect(hint()?.textContent).toBe("Pick what happens next to save");
    const save = tile("Save");
    expect(save.disabled).toBe(false);
    await act(async () => save.click());
    expect(fetchMock).not.toHaveBeenCalled();
    expect(hint()?.getAttribute("data-nudged")).toBe("true");
    // The missing step lights up, and again on the next tap.
    const step = () => host.querySelector("[data-nudge]");
    expect(step()?.getAttribute("data-nudge")).toBe("odd");
    expect(step()?.textContent).toContain("What happens next?");
    await act(async () => save.click());
    expect(step()?.getAttribute("data-nudge")).toBe("even");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("pre-fills No network when the phone had none", async () => {
    await show(lead("new"), heard("no_network"));
    expect(tile("No network").getAttribute("aria-pressed")).toBe("true");
    expect(host.textContent).toContain("Your phone says it had no network.");
  });

  it("pre-fills Cut the call when they declined", async () => {
    await show(lead("follow_up"), heard("rejected"));
    expect(tile("Cut the call").getAttribute("aria-pressed")).toBe("true");
    expect(host.textContent).toContain("they cut the call");
  });

  it("keeps only open stages", () => {
    expect(stageAfterTalk("follow_up")).toBe("follow_up");
    expect(stageAfterTalk("interested")).toBe("interested");
    expect(stageAfterTalk("not_connected")).toBeNull();
    expect(stageAfterTalk("won")).toBeNull();
    expect(missedReason("no_network")).toBe("out_of_coverage");
  });
});
