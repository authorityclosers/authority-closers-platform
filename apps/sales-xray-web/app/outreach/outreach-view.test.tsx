// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// Outreach, "what the owner sent" (v1.95): made-up people and leads only.
const nav = vi.hoisted(() => ({
  search: "",
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/outreach",
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));
const api = vi.hoisted(() => ({ read: vi.fn(), senders: vi.fn() }));
vi.mock("./outreach-client", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readOutreach: api.read,
  readSenders: api.senders,
}));
vi.mock("../leads/leads-client", () => ({
  readTeam: () =>
    Promise.resolve({
      reps: [{ person_id: "p2", name: "Rohan Fictional" }],
    }),
}));

import type { OutreachPage, TouchView } from "./outreach-client";
import { OutreachView, periodOf, queryFrom } from "./outreach-view";
import { teamDay, whatWords, whenWords } from "./outreach-words";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const touch = (over: Partial<TouchView> = {}): TouchView => ({
  touch_id: "t1",
  lead_id: "l1",
  channel: "whatsapp",
  content_kind: "text",
  initiated: "outreach",
  sender_type: "person",
  by_name: "Anjali Fictional",
  person_id: "p1",
  sender_id: null,
  sender_label: null,
  automation: null,
  via: "cloud",
  provider: "meta_cloud",
  summary: "Sent the price list",
  template_name: null,
  attachment: null,
  status: "delivered",
  status_at: null,
  sent_at: "2026-11-21T05:30:00Z",
  counted: true,
  verdict: "ok",
  after_block: false,
  override_by_name: null,
  override_reason: null,
  replied_at: null,
  event_id: null,
  ...over,
});
const page = (over: Partial<OutreachPage> = {}): OutreachPage => ({
  filter: {
    view: "leads",
    by: null,
    channel: null,
    date_from: "2026-11-16",
    date_to: "2026-11-22",
    replied: "any",
    over: false,
    locked_to_self: false,
  },
  hero: {
    touches: 14,
    leads: 6,
    replied: 2,
    past_limit: 1,
    leads_added: null,
    period: "Last 7 days",
    words: "14 touches · 6 leads · 2 replied",
    sentence: "1 was sent past a limit.",
  },
  leads: [
    {
      lead_id: "l1",
      name: "Asha Fictional",
      added_by_person_id: "p1",
      added_by_name: "Anjali Fictional",
      added_at: "2026-11-20T05:00:00Z",
      touches: 2,
      last_touch_at: "2026-11-21T05:30:00Z",
      replied: true,
      received: [
        touch(),
        touch({
          touch_id: "t2",
          verdict: "warn",
          summary: "Followed up on the quote",
          replied_at: "2026-11-21T07:00:00Z",
        }),
      ],
    },
  ],
  touches: [],
  next_cursor: null,
  ...over,
});

let host: HTMLDivElement;
let root: Root;
const settle = () =>
  act(async () => {
    for (let n = 0; n < 6; n++) await Promise.resolve();
  });
beforeEach(() => {
  nav.search = "";
  nav.replace.mockReset();
  api.read.mockReset();
  api.senders.mockReset();
  api.senders.mockResolvedValue([]);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("reads the filter from the address and names the period pill", () => {
  const now = Date.parse("2026-11-22T06:00:00Z");
  const query = queryFrom(
    new URLSearchParams("view=touches&by=person:me&over=true&replied=no_reply"),
  );
  expect(query).toMatchObject({
    view: "touches",
    by: "person:me",
    over: true,
    replied: "no_reply",
  });
  expect(periodOf({}, now)).toBe("week");
  expect(periodOf({ from: teamDay(now), to: teamDay(now) }, now)).toBe("today");
  expect(periodOf({ from: teamDay(now, 29) }, now)).toBe("month");
  expect(periodOf({ from: "2026-10-01", to: "2026-10-05" }, now)).toBeNull();
});

it("says what was sent and when, in plain words", () => {
  const now = Date.parse("2026-11-22T06:00:00Z");
  expect(whenWords("2026-11-22T05:32:00Z", now)).toBe("Today 11:02 am");
  expect(whenWords("2026-11-21T12:40:00Z", now)).toBe("Yesterday 6:10 pm");
  expect(whatWords(touch({ summary: null, template_name: "price_list" }))).toBe(
    "Template: price_list",
  );
  expect(
    whatWords(touch({ summary: null, attachment: { name: "Quote.pdf" } })),
  ).toBe("Quote.pdf");
});

it("shows the hero and each lead with what it received", async () => {
  api.read.mockResolvedValue(page());
  await act(async () => root.render(<OutreachView />));
  await settle();
  expect(api.read).toHaveBeenCalledWith(
    expect.objectContaining({ view: "leads", by: null }),
    expect.anything(),
  );
  expect(host.querySelector("h2")?.textContent).toBe(
    "14 touches · 6 leads · 2 replied",
  );
  expect(host.textContent).toContain("1 was sent past a limit.");
  const lead = host.querySelector("details")!;
  expect(lead.textContent).toContain("Asha Fictional");
  expect(lead.textContent).toContain("Added by Anjali Fictional");
  expect(lead.textContent).toContain("What Asha received");
  expect(lead.textContent).toContain("Sent the price list");
  expect(lead.textContent).toContain("Past a limit");
  expect(lead.querySelector('a[href="/leads?lead=l1"]')).not.toBeNull();
  // The By choices: everyone, me, the team.
  const by = host.querySelector<HTMLSelectElement>('select[aria-label="By"]')!;
  expect([...by.options].map((option) => option.textContent)).toEqual([
    "Everyone",
    "Me",
    "Rohan Fictional",
  ]);
});

it("puts the filters in the address", async () => {
  api.read.mockResolvedValue(page());
  await act(async () => root.render(<OutreachView />));
  await settle();
  const today = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Today",
  )!;
  await act(async () => today.click());
  expect(nav.replace.mock.calls[0][0]).toMatch(
    /^\/outreach\?from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}$/,
  );
  const byMessage = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "By message",
  )!;
  await act(async () => byMessage.click());
  expect(nav.replace.mock.calls[1][0]).toBe("/outreach?view=touches");
});

it("lists each message on By message, with a way to its lead", async () => {
  nav.search = "view=touches";
  api.read.mockResolvedValue(
    page({
      filter: { ...page().filter, view: "touches" },
      leads: [],
      touches: [touch({ channel: "email", summary: "Sent the brochure" })],
    }),
  );
  await act(async () => root.render(<OutreachView />));
  await settle();
  expect(host.textContent).toContain("Sent the brochure");
  expect(host.querySelector('a[href="/leads?lead=l1"]')?.textContent).toBe(
    "Open lead",
  );
});

it("locks a seller's By to themselves", async () => {
  api.read.mockResolvedValue(
    page({
      filter: { ...page().filter, by: "person:me", locked_to_self: true },
    }),
  );
  await act(async () => root.render(<OutreachView />));
  await settle();
  expect(host.querySelector('select[aria-label="By"]')).toBeNull();
  expect(host.textContent).toContain("By: You");
  expect(api.senders).not.toHaveBeenCalled();
});

it("says plainly when nothing was sent", async () => {
  api.read.mockResolvedValue(page({ leads: [] }));
  await act(async () => root.render(<OutreachView />));
  await settle();
  expect(host.textContent).toContain("Nothing sent in this period");
});
