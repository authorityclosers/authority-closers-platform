// v1.95 (owner, 22 Nov 2026: "every message we send is tracked, so we never
// feel spammy"): the counter line, the guard before a send, a manager's Send
// anyway, the touch lines and the touch sheet.
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

import type { OutreachGuard, TouchView } from "./leads-client";
import {
  chipWords,
  OutreachLine,
  pastLimitWords,
  SendGuard,
  senderName,
  slotWords,
  touchSender,
  TouchLine,
  TouchSheet,
  whyWords,
} from "./outreach";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const LEAD = "11111111-1111-4111-8111-111111111111";
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const guard = (over: Partial<OutreachGuard> = {}): OutreachGuard => ({
  channel: "whatsapp",
  verdict: "ok",
  reasons: [],
  words: "Last touched 2 days ago · 1 touch this week",
  counts: { today: 0, week: 1, unanswered: 1, calls_week: 0 },
  next_ok_at: null,
  opted_out: false,
  override: { possible: false, who: null },
  override_id: null,
  ...over,
});

const held = guard({
  verdict: "block",
  words: "Last touched today at 11:02 · 3 touches this week",
  reasons: [
    { code: "week_cap", words: "3 touches in the last 7 days", level: "block" },
  ],
  counts: { today: 1, week: 3, unanswered: 3, calls_week: 0 },
  next_ok_at: "2026-11-27T04:30:00Z",
  override: { possible: true, who: "manager" },
});

const touch = (over: Partial<TouchView> = {}): TouchView => ({
  touch_id: "t1",
  channel: "whatsapp",
  sender_type: "person",
  by_name: "Priya Deshmukh",
  sender_label: null,
  automation: null,
  via: "cloud",
  summary: "Sent the brochure",
  status: "delivered",
  sent_at: "2026-11-21T05:00:00Z",
  counted: true,
  replied_at: null,
  ...over,
});

const button = (words: string) =>
  [...document.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(words),
  ) as HTMLButtonElement | undefined;

it("says the counter calmly, with a chip and why when it holds", async () => {
  await act(async () => root.render(<OutreachLine guard={guard()} />));
  expect(host.textContent).toContain("Last touched 2 days ago");
  expect(host.querySelector("[data-verdict] span[data-verdict]")).toBeNull();
  await act(async () => root.render(<OutreachLine guard={held} />));
  expect(chipWords(held)).toBe("3 this week");
  // The count is said once (the counter, the chip): the why is short.
  expect(whyWords(held)).toMatch(/^At the weekly limit · OK again /);
  expect(host.textContent).toContain("3 this week");
  // A stop is never OK again by waiting.
  expect(
    whyWords(
      guard({
        verdict: "block",
        opted_out: true,
        reasons: [{ code: "opted_out", words: "Said stop", level: "block" }],
      }),
    ),
  ).toBe("Said stop · nobody can send past a stop");
});

it("holds a seller's send and says why; a manager may send anyway with a reason", async () => {
  const fetchMock = vi.fn(async () =>
    Response.json({ override_id: "o1", expires_at: "2026-11-22T06:00:00Z" }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await act(async () =>
    root.render(
      <SendGuard
        leadId={LEAD}
        name="Ravi"
        guard={held}
        manager={false}
        onPassed={() => undefined}
      >
        <button type="button">Open WhatsApp</button>
      </SendGuard>,
    ),
  );
  expect(button("Open WhatsApp")).toBeUndefined();
  expect(button("Send anyway")).toBeUndefined();
  expect(host.textContent).toContain("so Ravi never feels chased");
  // One way on: a follow-up for when it is OK again.
  const booked = vi.fn(async () => undefined);
  await act(async () =>
    root.render(
      <SendGuard
        leadId={LEAD}
        name="Ravi Kulkarni"
        guard={held}
        manager={false}
        onPassed={() => undefined}
        onFollowUp={booked}
      >
        <button type="button">Open WhatsApp</button>
      </SendGuard>,
    ),
  );
  await act(async () => button("Set follow-up for")!.click());
  expect(booked).toHaveBeenCalledWith(new Date(held.next_ok_at!));
  const passed = vi.fn();
  await act(async () =>
    root.render(
      <SendGuard
        leadId={LEAD}
        name="Ravi"
        guard={held}
        manager
        onPassed={passed}
      >
        <button type="button">Open WhatsApp</button>
      </SendGuard>,
    ),
  );
  await act(async () => button("Send anyway")!.click());
  // In the send's own place, never a sheet over it; it waits for a reason.
  expect(document.querySelector("dialog[open]")).toBeNull();
  const sheetSend = () =>
    host.querySelector<HTMLButtonElement>(
      '[data-sx-feature="outreach_send_anyway"]',
    )!;
  expect(sheetSend().disabled).toBe(true);
  await act(async () => button("The lead asked for it")!.click());
  expect(sheetSend().disabled).toBe(false);
  await act(async () => sheetSend().click());
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
  const [url, init] = fetchMock.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(url).toContain(`/leads/${LEAD}/overrides`);
  expect(JSON.parse(String(init.body))).toMatchObject({
    channel: "whatsapp",
    reason_key: "lead_asked",
  });
  expect(passed).toHaveBeenCalledTimes(1);
});

it("says who sent a touch, what, its delivery, the reply and a send past the limit", async () => {
  await act(async () =>
    root.render(
      <TouchLine
        touch={touch({
          replied_at: "2026-11-21T07:00:00Z",
          after_block: true,
          override_by_name: "Shivam",
          override_reason: "lead_asked",
        })}
      />,
    ),
  );
  expect(host.textContent).toContain("Priya Deshmukh · “Sent the brochure”");
  expect(host.textContent).toContain("Delivered");
  expect(host.textContent).toContain("Replied");
  expect(host.textContent).toContain(
    "Sent anyway by Shivam · lead asked for it",
  );
  expect(
    pastLimitWords(
      touch({
        sender_type: "automation",
        automation: "drip",
        after_block: true,
      }),
    ),
  ).toBe("Sent anyway by Drip");
});

it("lists the touches a page at a time", async () => {
  const fetchMock = vi.fn(async (url: string) =>
    url.includes("cursor=")
      ? Response.json({
          touches: [touch({ touch_id: "t2", summary: "First hello" })],
          next_cursor: null,
        })
      : Response.json({ touches: [touch()], next_cursor: "c2" }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await act(async () =>
    root.render(
      <TouchSheet open leadId={LEAD} name="Ravi" onClose={() => undefined} />,
    ),
  );
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
  expect(document.body.textContent).toContain("Sent the brochure");
  await act(async () => button("Show older")!.click());
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
  expect(document.body.textContent).toContain("First hello");
  expect(button("Show older")).toBeUndefined();
});

it("offers a held seller's follow-up in work hours, said like the hold", async () => {
  // v1.95 judge round 2: "rests until Thu 3 Dec" over a button for 9:09 pm.
  const restEnds = new Date("2026-12-02T15:39:00Z");
  const opens = new Date("2026-12-03T04:30:00Z");
  const booked = vi.fn(async () => undefined);
  await act(async () =>
    root.render(
      <SendGuard
        leadId={LEAD}
        name="Ravi"
        guard={{ ...held, next_ok_at: restEnds.toISOString() }}
        manager={false}
        onPassed={() => undefined}
        onFollowUp={booked}
        workSlot={(at) => (at < opens ? opens : at)}
      >
        <button type="button">Open WhatsApp</button>
      </SendGuard>,
    ),
  );
  const follow = button("Set follow-up for")!;
  expect(follow.textContent).toBe(`Set follow-up for ${slotWords(opens)}`);
  expect(slotWords(opens)).toMatch(/^Thu 3 Dec, \d{1,2}:\d{2} (am|pm)$/);
  await act(async () => follow.click());
  expect(booked).toHaveBeenCalledWith(opens);
});

it("names an outside sender in words, never by its slug", () => {
  expect(senderName("sx-engage")).toBe("SX Engage");
  expect(senderName("lead_bot")).toBe("Lead bot");
  expect(senderName("First reply")).toBe("First reply");
  expect(
    touchSender(
      touch({
        sender_type: "automation",
        by_name: null,
        sender_label: "sx-engage",
      }),
    ),
  ).toBe("SX Engage");
});

it("moves the chip with the counter's last part", async () => {
  await act(async () => root.render(<OutreachLine guard={held} />));
  const chip = host.querySelector("span[data-verdict]")!;
  // One box: never the chip on a line alone (v1.96, the 1440 pane).
  expect(chip.parentElement?.textContent).toBe(
    "3 touches this week 3 this week",
  );
  expect(chip.parentElement?.className).toMatch(/partLast/);
});
