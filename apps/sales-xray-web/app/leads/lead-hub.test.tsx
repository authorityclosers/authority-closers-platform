// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: unknown; href: string }) => (
    <a href={href}>{children as never}</a>
  ),
}));

import { chatDays, chatDayTitle } from "./lead-chats";
import { History } from "./lead-sheet";
import type { LeadEvent } from "./leads-client";
import type { SocialConversation } from "./social-client";
import type { WaConversation } from "./whatsapp-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The lead hub (approved map, slice 6, 22 Oct 2026): one timeline under the
// call; chats one line per app per day, the newest call's summary under it.
const LEAD = "11111111-1111-4111-8111-111111111111";

const wa = (messages: WaConversation["messages"]): WaConversation => ({
  configured: true,
  connected: true,
  numbers: [],
  messages,
  windowOpen: true,
  optedIn: true,
  templates: [],
});
const message = (at: string, direction: "in" | "out", text: string) => ({
  id: `${at}-${direction}`,
  direction,
  kind: "text",
  text,
  status: "delivered",
  at,
});

const event = (kind: LeadEvent["kind"], at: string, extra = {}): LeadEvent =>
  ({
    kind,
    at,
    actor_name: "Rahul Example",
    stage: null,
    stage_label: null,
    reason: null,
    reason_label: null,
    connected: kind === "call" ? true : null,
    note: kind === "note" ? "Wants a site visit" : null,
    next_action_at: null,
    owner_name: null,
    previous_owner_name: null,
    allocation_reason: null,
    source_label: null,
    ...extra,
  }) as LeadEvent;

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
});

it("folds a day's chat into one line per app, newest first", () => {
  const social: SocialConversation = {
    configured: true,
    connected: true,
    threads: [
      {
        accountId: "page-1",
        channel: "instagram",
        place: "Fictional Homes",
        messages: [message("2026-10-22T06:00:00Z", "in", "Price list please")],
        windowOpen: true,
        humanAgent: false,
      },
    ],
  };
  const days = chatDays(
    LEAD,
    wa([
      message("2026-10-21T05:00:00Z", "in", "Hello"),
      message("2026-10-22T04:00:00Z", "in", "Is the 2 BHK still free?"),
      message("2026-10-22T04:05:00Z", "out", "Yes, come on Sunday"),
      message("2026-10-22T04:06:00Z", "in", "Great"),
    ]),
    social,
  );
  expect(days.map((day) => [day.app, day.count, day.inbound])).toEqual([
    ["instagram", 1, 1],
    ["whatsapp", 3, 2],
    ["whatsapp", 1, 1],
  ]);
  expect(chatDayTitle(days[1])).toBe("3 WhatsApp messages");
  expect(days[1].last).toEqual({ text: "Great", mine: false });
  expect(days[1].href).toContain(LEAD);
  // Nothing set up: no lines.
  expect(chatDays(LEAD, { ...wa([]), connected: false }, null)).toEqual([]);
});

it("puts chats among calls and notes by time, and the summary under the newest call", async () => {
  const events = [
    event("note", "2026-10-22T07:00:00Z"),
    event("call", "2026-10-22T03:00:00Z", {
      submission_id: "22222222-2222-4222-8222-222222222222",
    }),
    event("call", "2026-10-21T03:00:00Z", {
      submission_id: "33333333-3333-4333-8333-333333333333",
    }),
  ];
  const chats = chatDays(
    LEAD,
    wa([message("2026-10-22T05:00:00Z", "in", "See you Sunday")]),
    null,
  );
  await act(async () =>
    root.render(
      <History
        events={events}
        chats={chats}
        brief={<p>What the last call said</p>}
      />,
    ),
  );
  const rows = [...host.querySelectorAll("li:not([aria-hidden])")].map(
    (row) => row.getAttribute("data-kind") ?? row.textContent,
  );
  // Note (07:00), chat (05:00), call (03:00) and its summary, then yesterday's call.
  expect(rows).toEqual([
    "note",
    "chat",
    "call",
    "What the last call said",
    "call",
  ]);
  const chat = host.querySelector('li[data-kind="chat"]')!;
  expect(chat.textContent).toContain("1 WhatsApp message");
  expect(chat.textContent).toContain("See you Sunday");
  expect(chat.querySelector("a")?.getAttribute("href")).toContain(LEAD);
});
