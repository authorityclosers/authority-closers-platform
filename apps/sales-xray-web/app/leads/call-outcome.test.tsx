import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => ({
  shown: [] as Array<{ title: string; message?: string }>,
}));
vi.mock("../notice-center", async (load) => ({
  ...(await load<typeof import("../notice-center")>()),
  notify: (notice: { title: string; message?: string }) =>
    notices.shown.push(notice),
}));

import {
  replayWrites,
  resetWrites,
  setWriteIdentity,
} from "../sync/write-queue";
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
    // Its reasons never repeat the heading (persona QA, 31 Oct 2026).
    expect(tile("Couldn't connect")).toBeDefined();
    expect(host.textContent).not.toContain("Call didn't go through");
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

describe("what the next stage asks after a call (persona QA, 31 Oct 2026)", () => {
  const withMoves = () =>
    ({
      ...lead("new"),
      stage_choices: [
        {
          key: "meeting_scheduled",
          kind: "interested",
          label: "Meeting Scheduled",
          meaning: "A meeting is booked",
        },
        {
          key: "lost",
          kind: "lost",
          label: "Closed / Lost",
          meaning: "They said no",
        },
      ],
      moves: [
        {
          step: "meeting_scheduled",
          label: "Meeting Scheduled",
          kind: "interested",
          milestone: "appointment_booked",
          group: "active",
          action: "move",
          needs: ["meeting"],
          asks: [],
          reasons: [],
        },
        {
          step: "lost",
          label: "Closed / Lost",
          kind: "lost",
          group: "lost",
          action: "close",
          needs: ["reason"],
          asks: [],
          reasons: [{ key: "price", label: "Price or budget" }],
        },
      ],
    }) as unknown as LeadDetail;

  it("asks when the meeting is, and why it was lost, before Save", async () => {
    await show(withMoves());
    await act(async () => tile("We talked").click());
    await act(async () => tile("Meeting Scheduled").click());
    expect(host.textContent).toContain("When is the meeting?");
    expect(host.textContent).toContain("Pick when the meeting is to save");
    await act(async () => tile("Closed / Lost").click());
    expect(host.textContent).toContain("Why was it lost?");
    expect(host.textContent).not.toContain("When is the meeting?");
    expect(host.textContent).toContain("Pick why to save");
    await act(async () => tile("Price or budget").click());
    expect(host.textContent).not.toContain("Pick why to save");
  });
});

describe("a Won deal after a call (revenue targets, with the asks above)", () => {
  it("still asks for the deal amount before Save", async () => {
    await show({
      ...lead("new"),
      stage_choices: [
        { key: "won", kind: "won", label: "Won", meaning: "They bought" },
      ],
      moves: [
        {
          step: "won",
          label: "Won",
          kind: "won",
          milestone: "won",
          group: "won",
          action: "close",
          needs: ["amount"],
          asks: [],
          reasons: [],
        },
      ],
    } as unknown as LeadDetail);
    await act(async () => tile("We talked").click());
    await act(async () => tile("Won").click());
    expect(host.textContent).toContain("Deal amount (₹)");
    expect(host.textContent).toContain("Add the deal amount to save");
    expect(host.textContent).not.toContain("When is the meeting?");
    // A phone's number keypad has no L: digits, read back in rupees (ph1-14).
    const amount = host.querySelector<HTMLInputElement>(
      'input[inputmode="decimal"]',
    )!;
    expect(amount.placeholder).toBe("60,000");
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(amount, "150000");
      amount.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(host.textContent).toContain("₹1,50,000");
  });
});

describe("where the lead went after Save (persona QA, 31 Oct 2026)", () => {
  it("says the stage it moved to and its next call, under the lead's name", async () => {
    const after = {
      ...lead("interested"),
      lead: {
        ...lead("interested").lead,
        next_action_at: "2026-11-03T05:30:00.000Z",
      },
    } as LeadDetail;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(after))),
    );
    notices.shown.length = 0;
    await show(lead("new"));
    await act(async () => tile("We talked").click());
    await act(async () => tile("Interested").click());
    await act(async () => tile("Save").click());
    const said = notices.shown.at(-1);
    expect(said?.title).toMatch(
      new RegExp(`^Moved to ${after.lead.stage_label} · next call `),
    );
    expect(said?.message).toBe(after.lead.name);
  });
});

describe("Undo on the Save card (31 Oct 2026)", () => {
  it("takes it back with Undo while the server offers it", async () => {
    const after = {
      ...lead("interested"),
      undo_result: { event_id: "answer-1", until: "2026-11-03T05:35:00.000Z" },
    } as LeadDetail;
    const fetchMock = vi.fn<typeof fetch>(
      async () => new Response(JSON.stringify(after)),
    );
    vi.stubGlobal("fetch", fetchMock);
    notices.shown.length = 0;
    await show(lead("new"));
    await act(async () => tile("We talked").click());
    await act(async () => tile("Interested").click());
    await act(async () => tile("Save").click());
    const card = notices.shown.at(-1) as {
      action?: { label: string; run: () => void };
    };
    expect(card.action?.label).toBe("Undo");
    await act(async () => card.action?.run());
    const asked = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(asked.at(-1)).toContain("/results/answer-1/undo");
    expect(notices.shown.at(-1)?.title).toMatch(/^Undone: back to /);
  });
});

// QA robot J221 (2 Nov 2026): a save the phone kept and sent later (Send now)
// kept saying "Not sent yet", with no Undo. It ends as a first-try save does.
describe("a save the phone kept, sent later", () => {
  afterEach(() => {
    resetWrites();
    window.localStorage.clear();
  });

  it("says where the lead went, with Undo, once it arrives", async () => {
    setWriteIdentity("seller-1");
    const after = {
      ...lead("interested"),
      lead: {
        ...lead("interested").lead,
        revision: 4,
        next_action_at: "2026-11-03T05:30:00.000Z",
      },
      undo_result: { event_id: "answer-1", until: "2026-11-03T05:35:00.000Z" },
    } as LeadDetail;
    let online = false;
    const fetchMock = vi.fn<typeof fetch>(async () => {
      if (!online) throw new TypeError("Failed to fetch");
      return new Response(JSON.stringify(after));
    });
    vi.stubGlobal("fetch", fetchMock);
    notices.shown.length = 0;
    const saved = vi.fn();
    await act(async () =>
      root.render(
        <CallOutcome
          detail={lead("new")}
          submitLabel="Save"
          attention={false}
          beforeSave={async () => lead("new")}
          onSaved={saved}
        />,
      ),
    );
    await act(async () => tile("We talked").click());
    await act(async () => tile("Interested").click());
    await act(async () => tile("Save").click());
    expect(host.textContent).toContain("Not sent yet");
    expect(saved).not.toHaveBeenCalled();
    expect(notices.shown.some((notice) => /^Moved to/.test(notice.title))).toBe(
      false,
    );

    // Back online: Send now sends what the phone kept.
    online = true;
    await act(async () => {
      await replayWrites({ force: true });
    });
    await act(async () => {
      for (let index = 0; index < 8; index += 1) await Promise.resolve();
    });
    const card = notices.shown.at(-1) as {
      title: string;
      action?: { label: string };
    };
    expect(card.title).toMatch(/^Moved to interested · next call /);
    expect(card.action?.label).toBe("Undo");
    expect(host.textContent).not.toContain("Not sent yet");
    expect(saved).toHaveBeenCalledTimes(1);
    // One answer: the same command id, refused once and then let through.
    const sends = fetchMock.mock.calls.filter((call) =>
      String(call[0]).endsWith("/dispose"),
    );
    expect(sends).toHaveLength(2);
    expect(
      new Set(sends.map((call) => JSON.parse(String(call[1]?.body)).command_id))
        .size,
    ).toBe(1);
  });
});

// ph2-16 (phone personas, 1 Nov 2026): plain answers over the organisation's
// own stages, and "I didn't call".
describe("plain answers after a call", () => {
  const ownStages = () =>
    ({
      ...lead("new"),
      stage_choices: [
        {
          key: "discussion_incomplete",
          kind: "follow_up",
          label: "Discussion incomplete",
          meaning: "Talk again",
        },
        { key: "lost", kind: "lost", label: "Lost", meaning: "They said no" },
      ],
      moves: [
        {
          step: "discussion_incomplete",
          label: "Discussion incomplete",
          kind: "follow_up",
          group: "active",
          action: "move",
          needs: ["next_action"],
          asks: [],
          reasons: [],
        },
        {
          step: "lost",
          label: "Lost",
          kind: "lost",
          group: "lost",
          action: "close",
          needs: ["reason"],
          asks: [],
          reasons: [{ key: "not_interested", label: "Not interested" }],
        },
      ],
    }) as unknown as LeadDetail;

  it("lands Not interested and Call back on the organisation's own stages", async () => {
    await show(ownStages());
    await act(async () => tile("We talked").click());
    const quick = host.querySelector('[aria-label="Quick answers"]')!;
    expect(
      [...quick.querySelectorAll("button")].map((b) => b.textContent),
    ).toEqual(["Not interested", "Call back", "Send details"]);
    await act(async () => tile("Not interested").click());
    expect(tile("Lost").getAttribute("aria-pressed")).toBe("true");
    await act(async () => tile("Call back").click());
    expect(tile("Discussion incomplete").getAttribute("aria-pressed")).toBe(
      "true",
    );
  });

  it("closes the question with I didn't call, saving nothing", async () => {
    const onSkip = vi.fn();
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    await act(async () =>
      root.render(
        <CallOutcome
          detail={ownStages()}
          submitLabel="Save"
          attention={false}
          beforeSave={async () => ownStages()}
          onSaved={() => undefined}
          onSkip={onSkip}
        />,
      ),
    );
    await act(async () => tile("I didn't call").click());
    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ph2-26 (phone QA, 1 Nov 2026): Undo took the answer's note out of sight.
describe("Undo keeps the answer's note", () => {
  it("says the note is kept in Notes", async () => {
    const after = {
      ...lead("interested"),
      undo_result: { event_id: "answer-2", until: "2026-11-03T05:35:00.000Z" },
    } as LeadDetail;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response(JSON.stringify(after))),
    );
    notices.shown.length = 0;
    await show(lead("new"));
    await act(async () => tile("We talked").click());
    await act(async () => tile("Interested").click());
    const box = host.querySelector<HTMLTextAreaElement>(
      'textarea[placeholder="What they need, what you promised"]',
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )!.set!.call(box, "Wants the EMI sheet");
      box.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => tile("Save").click());
    const card = notices.shown.at(-1) as { action?: { run: () => void } };
    await act(async () => card.action?.run());
    expect(notices.shown.at(-1)?.message).toContain(
      "your note is kept in Notes",
    );
  });
});
