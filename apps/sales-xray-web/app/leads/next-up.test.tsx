// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({
  notify: () => undefined,
  dismissNotice: () => undefined,
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { CallNext } from "./call-next";
import { daytimeRetry, inTeamHours, LeadSheet, talkedNext } from "./lead-sheet";
import { reportRows, WrapUpDone } from "./wrap-up";
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

// Dipak's Home + Leads handoff (31 Oct 2026, items 16-17): from Call Next, a
// missed call goes on through the list; a one-off call closes the question and
// stays on the lead (J213, 1 Nov 2026: a note or a follow-up often comes
// next). Since the wrap-up screen (round-2 board 1, 20 Nov 2026) the question
// is a screen of its own with four answers, and a one-off call ends on Saved
// with Back to the lead.
it.each([false, true])(
  "after a call opened with queue %s, a missed call saves",
  async (queue) => {
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
    expect(document.querySelector("[data-wrap-up]")).not.toBeNull();
    expect(tile("I didn't call")).toBeDefined();
    await act(async () => tile("No answer").click());
    expect(document.body.textContent).toContain("Step 2 of 2");
    await act(async () => tile("Save").click());
    await flush();
    expect(onClose).not.toHaveBeenCalled();
    if (queue) {
      expect(onNext).toHaveBeenCalledWith(ONE);
    } else {
      expect(onNext).not.toHaveBeenCalled();
      expect(document.body.textContent).toContain("Saved");
      await act(async () => tile("Back to Ravi").click());
      // Still on the lead, the question answered and gone.
      expect(document.body.textContent).toContain("Ravi Kulkarni");
      expect(document.body.textContent).not.toContain("How did the call");
      expect(tile("Log a call")).toBeDefined();
    }
    expect(document.querySelector('[class*="nextUp"]')).toBeNull();
  },
);

it("asks once when opened to log a call, then stays on the lead", async () => {
  const onClose = vi.fn();
  await act(async () =>
    root.render(
      <LeadSheet
        leadId={ONE}
        me={null}
        intent="log"
        onClose={onClose}
        onChanged={() => undefined}
      />,
    ),
  );
  await flush();
  expect(document.body.textContent).toContain("How did the call with Ravi go?");
  await act(async () => tile("No answer").click());
  await act(async () => tile("Save").click());
  await flush();
  await act(async () => tile("Back to Ravi").click());
  expect(onClose).not.toHaveBeenCalled();
  expect(document.body.textContent).toContain("Ravi Kulkarni");
  expect(document.body.textContent).not.toContain("How did the call");
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
  // The wrap-up screen asks, the phone's talk time under the lead's name.
  expect(document.querySelector("[data-wrap-up]")).not.toBeNull();
  // The phone says they talked: straight to step 2, one tap back to change.
  expect(text).toContain("Step 2 of 2");
  expect(text).toContain("What happens next?");
  expect(text).toContain("Talked 1\u00a0min 22\u00a0s · just now");
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

// Round-2 board 1 (option B, 20 Nov 2026): after a call the wrap-up screen
// has four big answers; Busy sets the next try in the same tap, and a call
// that connected ends on Saved, the report on its way and Call next lead.
it("wraps up a call: busy sets the next try, a talk ends with Call next lead", async () => {
  const onCallNext = vi.fn();
  await act(async () =>
    root.render(
      <LeadSheet
        leadId={ONE}
        me={null}
        intent="log"
        onClose={() => undefined}
        onChanged={() => undefined}
        onCallNext={onCallNext}
      />,
    ),
  );
  await flush();
  for (const label of [
    "We talked",
    "No answer",
    "Busy, call back",
    "Wrong number",
  ])
    expect(tile(label), label).toBeDefined();
  await act(async () => tile("Busy, call back").click());
  expect(document.body.textContent).toContain("When to try again?");
  expect(document.body.textContent).toContain("In 1 hour");
  // Back to the four answers, nothing saved.
  await act(async () =>
    (
      document.querySelector(
        'button[aria-label="Change how it went"]',
      ) as HTMLButtonElement
    ).click(),
  );
  expect(tile("Wrong number")).toBeDefined();
});

// v1.93 (round-2 board 1, option B, owner 22 Nov 2026: "Yes, build them"):
// step 2 starts ready to save, the likely next step chosen and the follow-up
// time filled; the other stages one tap down; one back arrow.
it("starts step 2 ready: Interested chosen, tomorrow's time, one way back", async () => {
  await act(async () =>
    root.render(
      <LeadSheet
        leadId={ONE}
        me={null}
        intent="log"
        onClose={() => undefined}
        onChanged={() => undefined}
      />,
    ),
  );
  await flush();
  expect(document.body.textContent).toContain("Step 1 of 2");
  await act(async () => tile("We talked").click());
  expect(document.body.textContent).toContain("Step 2 of 2");
  const group = document.querySelector('[aria-label="Next step"]')!;
  expect(
    [...group.querySelectorAll("button")].map((b) => b.textContent),
  ).toEqual(["Interested", "Send details", "Call back", "Not interested"]);
  expect(group.querySelector('[aria-pressed="true"]')?.textContent).toBe(
    "Interested",
  );
  // Nothing missing to say: Save is ready.
  expect(document.body.textContent).not.toContain("to save");
  expect(
    document.querySelectorAll('button[aria-label="Change how it went"]'),
  ).toHaveLength(1);
  expect(tile("Tomorrow").getAttribute("aria-pressed")).toBe("true");
  // The organisation's other stages, one tap down.
  expect(document.querySelector('[aria-label="What happens next"]')).toBeNull();
  await act(async () => tile("Change stage").click());
  // Only the stages none of the four is, under "Stage", none lit twice
  // (v1.93 judge round 2); the toggle keeps its words.
  const others = document.querySelector('[aria-label="What happens next"]')!;
  expect(
    [...others.querySelectorAll("button")].map((b) => b.textContent),
  ).toEqual(["Won"]);
  expect(others.querySelector('[aria-pressed="true"]')).toBeNull();
  expect(others.parentElement?.textContent).toMatch(/^Stage/);
  expect(tile("Change stage").getAttribute("aria-expanded")).toBe("true");
  await act(async () => tile("Save").click());
  await flush();
  const sent = vi
    .mocked(fetch)
    .mock.calls.find(([url]) => String(url).endsWith("/dispose"));
  const body = JSON.parse(String(sent?.[1]?.body));
  expect(body).toMatchObject({ connected: true, stage: "interested" });
  expect(new Date(body.follow_up_at).getTime()).toBeGreaterThan(Date.now());
  expect(document.body.textContent).toContain("Saved");
});

it("says only what it knows of the report on its way", () => {
  expect(reportRows(null, "Ravi").rows).toEqual([]);
  expect(reportRows(null, "Ravi").line).toContain("about 2 min");
  expect(
    reportRows(
      { done: 4, label: "Analysing", stuck: false, recording: "arrived" },
      "Ravi",
    ).rows,
  ).toEqual([
    { label: "Recording found", state: "done" },
    { label: "Uploaded", state: "done" },
    { label: "Reading the call · about 2 min", state: "now" },
  ]);
  expect(
    reportRows(
      {
        done: 0,
        label: "No recording after 30 minutes",
        stuck: false,
        ended: true,
        recording: "not found",
      },
      "Ravi",
    ).title,
  ).toBe("No recording for this call");
});

it("ends a talk on Saved with the report on its way and one Call next lead", async () => {
  const saved = {
    ...detail(ONE, "Ravi Kulkarni"),
    lead: { ...detail(ONE, "Ravi Kulkarni").lead, stage_label: "Interested" },
  };
  const onCallNext = vi.fn();
  await act(async () =>
    root.render(
      <WrapUpDone
        saved={saved}
        talked
        reportExpected
        onCallNext={onCallNext}
        onBack={() => undefined}
      />,
    ),
  );
  expect(host.textContent).toContain("Your call report is on its way");
  const next = tile("Call next lead");
  expect(next.className).toMatch(/primary/);
  expect(tile("Back to Ravi").className).toMatch(/secondary/);
  await act(async () => next.click());
  expect(onCallNext).toHaveBeenCalledTimes(1);
  // Undo sits on the Saved screen itself, only while the server offers it.
  expect(tile("Undo")).toBeUndefined();
  const onUndo = vi.fn();
  await act(async () =>
    root.render(
      <WrapUpDone
        saved={saved}
        talked
        reportExpected
        onUndo={onUndo}
        onBack={() => undefined}
      />,
    ),
  );
  await act(async () => tile("Undo").click());
  expect(onUndo).toHaveBeenCalledTimes(1);
});

// v1.93 judge round 3: a missed call's next try fell at 4 am (the desk's own
// gap). It is chosen in the working day and sent as the follow-up.
it("puts a missed call's next try in the working day", () => {
  const at = (iso: string) => new Date(iso);
  // 2 pm, first try: in 1 hour, inside the day.
  expect(daytimeRetry(0, at("2026-11-23T14:00:00")).pick).toBe("hour");
  // 8 pm, first try: 9 pm is late, so tomorrow 10:00 (the Tomorrow chip).
  expect(daytimeRetry(0, at("2026-11-23T20:00:00")).pick).toBe("morning");
  // 4 am, later try: 4 am tomorrow is early, so 10:00 that morning (the
  // Tomorrow chip).
  const early = daytimeRetry(2, at("2026-11-23T04:02:00"));
  expect(early.pick).toBe("morning");
  expect(early.custom).toBe("2026-11-24T10:00");
  // 3 pm, later try: the same time tomorrow, inside the day.
  expect(daytimeRetry(2, at("2026-11-23T15:00:00")).custom).toBe(
    "2026-11-24T15:00",
  );
});

it("sends the missed call's next try it shows", async () => {
  await act(async () =>
    root.render(
      <LeadSheet
        leadId={ONE}
        me={null}
        intent="log"
        onClose={() => undefined}
        onChanged={() => undefined}
      />,
    ),
  );
  await flush();
  await act(async () => tile("No answer").click());
  const chosen = document.querySelector(
    '[aria-label="Quick times"] [aria-pressed="true"]',
  );
  // One of the chips, or a time of its own: either way a time is shown.
  expect(document.body.textContent).toMatch(/· \d{1,2}:\d{2}/);
  await act(async () => tile("Save").click());
  await flush();
  const sent = vi
    .mocked(fetch)
    .mock.calls.find(([url]) => String(url).endsWith("/dispose"));
  const body = JSON.parse(String(sent?.[1]?.body));
  expect(body).toMatchObject({ connected: false, reason: "did_not_pick" });
  const when = new Date(body.follow_up_at);
  const minutes = when.getHours() * 60 + when.getMinutes();
  expect(minutes).toBeGreaterThanOrEqual(9 * 60 + 30);
  expect(minutes).toBeLessThanOrEqual(19 * 60 + 30);
  expect(chosen === null || chosen.textContent !== "").toBe(true);
});

// v1.93.1 (owner, 22 Nov 2026): the next try uses the team's real hours, in the
// team's clock, skipping days off; never before the team opens.
it("puts the next try in the team's own hours, skipping days off", () => {
  const ist = (wall: string) => new Date(`${wall}+05:30`);
  const monSat = {
    days: [0, 1, 2, 3, 4, 5],
    start: "09:30",
    end: "19:30",
    timezone: "Asia/Kolkata",
  };
  // Inside the hours: kept as it is.
  expect(inTeamHours(ist("2026-11-27T15:00:00"), monSat)).toEqual(
    ist("2026-11-27T15:00:00"),
  );
  // Saturday night: Sunday is off, so Monday 10:00.
  expect(inTeamHours(ist("2026-11-28T21:00:00"), monSat)).toEqual(
    ist("2026-11-30T10:00:00"),
  );
  // Early morning: that day's 10:00, after the 9:30 opening.
  expect(inTeamHours(ist("2026-11-27T04:02:00"), monSat)).toEqual(
    ist("2026-11-27T10:00:00"),
  );
  // A team that opens at 10:30: never before it opens.
  expect(
    inTeamHours(ist("2026-11-27T06:00:00"), { ...monSat, start: "10:30" }),
  ).toEqual(ist("2026-11-27T10:30:00"));
  // A missed call on Saturday at 7 pm: 8 pm is closed, Monday 10:00.
  const missed = daytimeRetry(0, ist("2026-11-28T19:00:00"), monSat);
  expect(new Date(missed.custom).getTime()).toBe(
    new Date(
      inTeamHours(ist("2026-11-30T10:00:00"), monSat).getTime(),
    ).setSeconds(0, 0),
  );
  // After a talk on Friday, with a Monday to Friday team: Monday 10:00.
  const weekdays = { ...monSat, days: [0, 1, 2, 3, 4] };
  const talked = talkedNext(ist("2026-11-27T15:00:00"), weekdays);
  expect(talked.pick).toBe("custom");
  expect(new Date(talked.custom).getTime()).toBe(
    ist("2026-11-30T10:00:00").getTime(),
  );
});

// v1.94 (the real-iPhone check, 22 Nov 2026): with the keyboard up, the
// wrap-up fits what is still seen, so Save rides just above the keyboard.
it("fits the wrap-up to the visual viewport while the keyboard is up", async () => {
  const view = new EventTarget() as EventTarget & {
    height: number;
    offsetTop: number;
  };
  view.height = 844;
  view.offsetTop = 0;
  vi.stubGlobal("visualViewport", view);
  Object.defineProperty(window, "innerHeight", {
    value: 844,
    configurable: true,
  });
  await act(async () =>
    root.render(
      <LeadSheet
        leadId={ONE}
        me={null}
        intent="log"
        onClose={() => undefined}
        onChanged={() => undefined}
      />,
    ),
  );
  await flush();
  const layer = document.querySelector<HTMLElement>("[data-wrap-up]")!;
  expect(layer.style.height).toBe("");
  view.height = 420;
  view.offsetTop = 60;
  await act(async () => view.dispatchEvent(new Event("resize")));
  expect(layer.style.top).toBe("60px");
  expect(layer.style.height).toBe("420px");
  view.height = 844;
  view.offsetTop = 0;
  await act(async () => view.dispatchEvent(new Event("resize")));
  expect(layer.style.height).toBe("");
});

// v1.94 (the real-iPhone check): Back from the wrap-up keeps the question on
// the lead (the W2 rule) and the Call band with it.
it("keeps the Call band when the question waits on the lead", async () => {
  await act(async () =>
    root.render(
      <LeadSheet
        leadId={ONE}
        me={null}
        intent="log"
        onClose={() => undefined}
        onChanged={() => undefined}
      />,
    ),
  );
  await flush();
  expect(document.querySelector("[data-call-band]")).toBeNull();
  await act(async () =>
    (
      document.querySelector(
        'button[aria-label="Back to Ravi Kulkarni"]',
      ) as HTMLButtonElement
    ).click(),
  );
  expect(document.querySelector("[data-wrap-up]")).toBeNull();
  expect(document.body.textContent).toContain("How did the call with Ravi go?");
  expect(document.querySelector("[data-call-band]")).not.toBeNull();
});
