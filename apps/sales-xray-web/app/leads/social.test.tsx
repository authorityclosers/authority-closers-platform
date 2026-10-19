import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  keywordList,
  socialText,
  socialWindowLine,
  type MessagingStatus,
  type SocialConversation,
  type SocialThread as Thread,
} from "./social-client";
import { SocialInbox } from "./social-inbox";
import { SocialSettings } from "./social-settings";
import { SocialThread } from "./social-thread";

vi.mock("next/navigation", () => ({
  useSearchParams: () =>
    new URLSearchParams("tab=integrations&messaging=connected"),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = new Date("2027-01-15T10:00:00Z");
const thread = (extra: Partial<Thread> = {}): Thread => ({
  accountId: "a1",
  channel: "messenger",
  place: "Messenger · Fictional Homes",
  messages: [
    {
      id: "m1",
      direction: "in",
      kind: "text",
      text: "Is the 3 BHK available?",
      status: "received",
      at: NOW.toISOString(),
    },
  ],
  windowOpen: true,
  windowClosesAt: new Date(NOW.getTime() + 3 * 3600_000).toISOString(),
  humanAgent: false,
  ...extra,
});
const PAGE = {
  id: "a1",
  pageId: "100200300",
  pageName: "Fictional Homes",
  igUsername: "fictional.homes",
  hasInstagram: true,
  settings: {
    messenger: true,
    instagram: true,
    humanAgent: false,
    firstReply: { on: false, text: null },
    outOfHours: { on: false, text: null },
    comments: [],
  },
};

let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string; body?: Record<string, unknown> }[];
let chat: SocialConversation;
let status: MessagingStatus;

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), {
    status: code,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  calls = [];
  chat = { configured: true, connected: true, threads: [thread()] };
  status = { configured: true, accounts: [PAGE], taken: [] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url.endsWith("/leads/l1/social") && method === "POST") {
        const sent = {
          id: `out${calls.length}`,
          direction: "out" as const,
          kind: "text",
          text: body.text,
          status: "sent",
          at: NOW.toISOString(),
          by: "Priya",
          humanAgent: body.humanAgent,
        };
        chat = {
          ...chat,
          threads: [
            {
              ...chat.threads[0],
              messages: [...chat.threads[0].messages, sent],
            },
          ],
        };
        return json(chat);
      }
      if (url.endsWith("/leads/l1/social")) return json(chat);
      if (url.endsWith("/social/inbox"))
        return json([
          {
            leadId: "l1",
            leadName: "Asha Fictional",
            channel: "instagram",
            lastText: "price?",
            lastAt: NOW.toISOString(),
            waiting: true,
            windowOpen: true,
          },
        ]);
      if (url.endsWith("/messaging/accounts/a1") && method === "PUT") {
        status = {
          ...status,
          accounts: [{ ...PAGE, settings: body }],
        };
        return json(status);
      }
      if (url.endsWith("/messaging/status")) return json(status);
      return json({ detail: "not here" }, 404);
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const render = async (node: ReactNode) => {
  await act(async () => root.render(node));
};

const type = async (
  field: HTMLInputElement | HTMLTextAreaElement,
  text: string,
) => {
  const setter = Object.getOwnPropertyDescriptor(
    Object.getPrototypeOf(field),
    "value",
  )?.set;
  await act(async () => {
    setter?.call(field, text);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

const button = (label: string) =>
  [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes(label),
  ) as HTMLButtonElement;

it("says how long replies last, and when only a person may answer", () => {
  expect(socialWindowLine(thread(), NOW)).toBe(
    "You can reply for 3 more hours.",
  );
  expect(
    socialWindowLine(thread({ windowOpen: false, windowClosesAt: null }), NOW),
  ).toContain("When they write again");
  expect(
    socialWindowLine(
      thread({ windowOpen: false, windowClosesAt: null, humanAgent: true }),
      NOW,
    ),
  ).toContain("within 7 days");
  expect(
    socialText({
      id: "c",
      direction: "in",
      kind: "comment",
      text: "price?",
      status: "received",
      at: NOW.toISOString(),
    }),
  ).toBe("Commented: price?");
  expect(keywordList(" price, site visit ,, ")).toEqual([
    "price",
    "site visit",
  ]);
});

it("replies on Messenger inside the 24-hour window", async () => {
  await render(<SocialThread leadId="l1" canSend />);
  expect(host.textContent).toContain("Messenger · Fictional Homes");
  expect(host.textContent).toContain("Is the 3 BHK available?");
  await type(
    host.querySelector(
      'textarea[aria-label="Messenger message"]',
    ) as HTMLTextAreaElement,
    "Yes, it is!",
  );
  await act(async () => button("Send").click());
  const sent = calls.find((call) => call.method === "POST");
  expect(sent?.body).toMatchObject({
    channel: "messenger",
    accountId: "a1",
    text: "Yes, it is!",
    humanAgent: false,
  });
  expect(host.textContent).toContain("Yes, it is!");
  expect(host.textContent).toContain("Priya · Sent");
});

it("after 24 hours lets a person answer with Meta's Human Agent rule, or waits", async () => {
  chat = {
    ...chat,
    threads: [
      thread({ windowOpen: false, windowClosesAt: null, humanAgent: true }),
    ],
  };
  await render(<SocialThread leadId="l1" canSend />);
  await type(
    host.querySelector("textarea") as HTMLTextAreaElement,
    "Sorry for the wait",
  );
  await act(async () => button("Send").click());
  expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({
    humanAgent: true,
  });

  chat = {
    ...chat,
    threads: [
      thread({ windowOpen: false, windowClosesAt: null, humanAgent: false }),
    ],
  };
  await act(async () => root.unmount());
  root = createRoot(host);
  await render(<SocialThread leadId="l1" canSend />);
  expect(host.querySelector("textarea")).toBeNull();
  expect(host.textContent).toContain("When they write again");
});

it("shows nothing on a lead without Messenger or Instagram messages", async () => {
  chat = { configured: true, connected: true, threads: [] };
  await render(<SocialThread leadId="l1" canSend />);
  expect(host.textContent).toBe("");
});

it("puts Messenger and Instagram conversations waiting for a reply on the desk", async () => {
  const opened: string[] = [];
  await render(<SocialInbox onOpen={(id) => opened.push(id)} />);
  expect(host.textContent).toContain("1 waiting for a reply");
  expect(host.textContent).toContain("Instagram · price?");
  await act(async () => button("Asha Fictional").click());
  expect(opened).toEqual(["l1"]);
});

it("connects Pages in Settings and saves a comment rule", async () => {
  await render(<SocialSettings />);
  expect(host.textContent).toContain("Messenger & Instagram");
  expect(host.textContent).toContain("Connected. Messages to your Page");
  expect(host.textContent).toContain("@fictional.homes");
  const connect = host.querySelector(
    'a[href="/v1/lead-desk/messaging/connect"]',
  ) as HTMLAnchorElement;
  expect(connect.textContent).toBe("Add a Page");

  await act(async () => button("Add a comment rule").click());
  const inputs = [
    ...host.querySelectorAll("fieldset input"),
  ] as HTMLInputElement[];
  await type(inputs[0], "price, site visit");
  await type(
    host.querySelector("fieldset textarea") as HTMLTextAreaElement,
    "Hi {first_name}, here are the prices.",
  );
  await act(async () => button("Save").click());
  const saved = calls.find((call) => call.method === "PUT");
  expect(saved?.url).toBe("/v1/lead-desk/messaging/accounts/a1");
  expect(saved?.body?.comments).toEqual([
    {
      on: true,
      keywords: ["price", "site visit"],
      reply: "Hi {first_name}, here are the prices.",
      publicReply: null,
    },
  ]);
  expect(host.textContent).toContain("Saved.");
});

it("stays hidden until AC's Messaging app is set up", async () => {
  status = { configured: false, accounts: [] };
  await render(<SocialSettings />);
  expect(host.textContent).toBe("");
});
