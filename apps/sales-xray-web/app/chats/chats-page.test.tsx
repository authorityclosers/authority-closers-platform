import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { WorkspaceAccessValue } from "../workspace-access";
import { ChatsRoute } from "./chats-page";

const mocks = vi.hoisted(() => ({
  access: null as WorkspaceAccessValue | null,
}));
vi.mock("../workspace-access", () => ({
  useWorkspaceAccess: () => mocks.access,
}));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({
    children,
    pageName,
  }: {
    children: ReactNode;
    pageName?: string;
  }) => <main data-page={pageName}>{children}</main>,
}));

const LEAD = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const ACCOUNT = "33333333-3333-4333-8333-333333333333";
const now = new Date();
const minutesAgo = (minutes: number) =>
  new Date(now.getTime() - minutes * 60000).toISOString();

let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string; body?: Record<string, unknown> }[];
let messages: Record<string, unknown>[];

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), {
    status: code,
    headers: { "content-type": "application/json" },
  });

const conversation = () => ({
  configured: true,
  connected: true,
  threads: [
    {
      accountId: ACCOUNT,
      channel: "messenger",
      place: "Messenger · Fictional Homes",
      messages,
      windowOpen: true,
      windowClosesAt: new Date(now.getTime() + 5 * 3600_000).toISOString(),
      humanAgent: false,
    },
  ],
});

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  window.history.replaceState(null, "", "/chats");
  mocks.access = {
    status: "ready",
    authenticated: true,
    context: {
      personId: "p-me",
      sessionId: "s1",
      tenantId: "t1",
    },
    workspaces: [],
  } as unknown as WorkspaceAccessValue;
  calls = [];
  messages = [
    {
      id: "m1",
      direction: "in",
      kind: "text",
      text: "Is the 2BHK still free?",
      status: "received",
      at: minutesAgo(6),
    },
    {
      id: "m2",
      direction: "out",
      kind: "text",
      text: "Yes, it is.",
      status: "read",
      at: minutesAgo(5),
      by: "Neha",
    },
    {
      id: "m3",
      direction: "in",
      kind: "image",
      text: null,
      status: "received",
      at: minutesAgo(4),
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url.endsWith("/v1/lead-desk/me"))
        return json({
          person_id: "p-me",
          name: "Neha",
          role: "member",
          can_manage: false,
        });
      if (url.endsWith("/sla"))
        return json({
          on: true,
          minutes: 10,
          alertManagers: false,
          targets: [],
        });
      if (url.endsWith("/social/inbox"))
        return json([
          {
            leadId: LEAD,
            leadName: "Asha Rao",
            channel: "messenger",
            lastText: null,
            lastAt: minutesAgo(4),
            waiting: true,
            windowOpen: true,
          },
          {
            leadId: OTHER,
            leadName: "Ravi Iyer",
            channel: "instagram",
            lastText: "Thanks!",
            lastAt: minutesAgo(90),
            waiting: false,
            windowOpen: true,
          },
        ]);
      if (url.endsWith("/whatsapp/inbox"))
        return json({ detail: "WhatsApp isn't set up." }, 409);
      if (url.endsWith(`/leads/${LEAD}/social`) && method === "POST") {
        messages = [
          ...messages,
          {
            id: "m4",
            direction: "out",
            kind: "text",
            text: body?.text,
            status: "sent",
            at: new Date().toISOString(),
            by: "Neha",
          },
        ];
        return json(conversation());
      }
      if (url.endsWith(`/leads/${LEAD}/social`)) return json(conversation());
      return json({ detail: "Not here." }, 404);
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
  vi.unstubAllGlobals();
});

const settle = async () => {
  for (let index = 0; index < 6; index += 1)
    await act(async () => {
      await Promise.resolve();
    });
};

it("lists chats waiting first with the channel, unread dot and reply clock", async () => {
  await act(async () => root.render(<ChatsRoute />));
  await settle();
  const rows = [
    ...host.querySelectorAll<HTMLButtonElement>(
      "ul[aria-label='Chats'] button",
    ),
  ];
  expect(rows.map((row) => row.querySelector("strong")?.textContent)).toEqual([
    "Asha Rao",
    "Ravi Iyer",
  ]);
  expect(rows[0].hasAttribute("data-unread")).toBe(true);
  expect(rows[0].textContent).toContain("A photo, file or sticker");
  expect(rows[0].textContent).toContain("4 min");
  expect(rows[1].hasAttribute("data-unread")).toBe(false);
  // A seller sees their own chats only: no Mine / Unassigned switch.
  expect(host.querySelector("[aria-label='Whose chats']")).toBeNull();
  expect(host.querySelector("main")?.dataset.page).toBe("Chats (1)");
});

it("opens a chat with day lines, bubbles and ticks, and sends a reply", async () => {
  await act(async () => root.render(<ChatsRoute />));
  await settle();
  const first = host.querySelector<HTMLButtonElement>(
    "ul[aria-label='Chats'] button",
  )!;
  await act(async () => first.click());
  await settle();
  expect(window.location.hash).toBe(`#chat=messenger:${LEAD}`);
  const chat = host.querySelector("section[aria-label='Chat with Asha Rao']")!;
  expect(chat).not.toBeNull();
  expect(chat.textContent).toContain("Today");
  expect(chat.textContent).toContain("Is the 2BHK still free?");
  expect(chat.querySelector("[aria-label='Read']")).not.toBeNull();
  expect(chat.textContent).toContain("Messenger · Fictional Homes");
  // Opening it clears its dot.
  expect(first.hasAttribute("data-unread")).toBe(false);

  const box = chat.querySelector<HTMLTextAreaElement>("textarea")!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!;
    setter.call(box, "We can visit on Saturday.");
    box.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    chat.querySelector<HTMLButtonElement>("button[aria-label='Send']")!.click(),
  );
  await settle();
  const sent = calls.find(
    (call) =>
      call.method === "POST" && call.url.endsWith(`/leads/${LEAD}/social`),
  );
  expect(sent?.body).toMatchObject({
    channel: "messenger",
    accountId: ACCOUNT,
    text: "We can visit on Saturday.",
    humanAgent: false,
  });
  expect(chat.textContent).toContain("We can visit on Saturday.");
  expect(box.value).toBe("");
});

it("says plainly why a closed chat can't be answered", async () => {
  window.history.replaceState(null, "", `/chats#chat=messenger:${LEAD}`);
  const closed = conversation();
  closed.threads[0].windowOpen = false;
  const original = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).endsWith(`/leads/${LEAD}/social`)
        ? json(closed)
        : original(input, init),
    ),
  );
  await act(async () => root.render(<ChatsRoute />));
  await settle();
  const chat = host.querySelector("section[aria-label^='Chat']")!;
  expect(chat.textContent).toContain("more than 24 hours old");
  expect(chat.querySelector("textarea")).toBeNull();
});
