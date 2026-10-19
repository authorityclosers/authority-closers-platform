import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ThreadView } from "./thread-view";

const LEAD = "11111111-1111-4111-8111-111111111111";
const ACCOUNT = "33333333-3333-4333-8333-333333333333";
const ago = (minutes: number) =>
  new Date(Date.now() - minutes * 60000).toISOString();

let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string; body?: Record<string, unknown> }[];
let whatsapp: Record<string, unknown>;
let ai: Record<string, unknown>;

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), {
    status: code,
    headers: { "content-type": "application/json" },
  });

const TEMPLATE = {
  name: "visit_reminder",
  language: "en",
  category: "UTILITY",
  status: "APPROVED",
  text: "Hi {{1}}, your site visit is on {{2}}.",
  parts: 2,
};

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  calls = [];
  whatsapp = {
    configured: true,
    connected: true,
    numbers: [
      {
        id: ACCOUNT,
        displayNumber: "+91 99990 10009",
        verifiedName: "Fictional Homes",
        autoReplies: { firstReply: { on: false }, outOfHours: { on: false } },
      },
    ],
    messages: [
      {
        id: "w1",
        direction: "in",
        kind: "text",
        text: "Please share the brochure",
        status: "received",
        at: ago(60 * 30),
      },
    ],
    windowOpen: false,
    windowClosesAt: null,
    optedIn: true,
    optInHow: "Wrote to us",
    templates: [
      TEMPLATE,
      { ...TEMPLATE, name: "draft_one", status: "PENDING" },
    ],
  };
  ai = {
    mode: "off",
    channels: [],
    ready: false,
    available: false,
    paused: false,
    handoffs: [],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url.endsWith(`/leads/${LEAD}/ai`)) return json(ai);
      if (url.endsWith(`/leads/${LEAD}/ai-draft`))
        return json({
          replyId: "r1",
          status: "drafted",
          draft: "Hi Asha, Saturday at 11 works. Shall I book it?",
          handoff: false,
          words: "",
        });
      if (url.endsWith(`/leads/${LEAD}/whatsapp/opt-in`)) {
        whatsapp = { ...whatsapp, optedIn: true, optInHow: body?.how };
        return json(whatsapp);
      }
      if (url.endsWith(`/leads/${LEAD}/whatsapp`) && method === "POST") {
        whatsapp = {
          ...whatsapp,
          messages: [
            ...(whatsapp.messages as unknown[]),
            {
              id: "w2",
              direction: "out",
              kind: "template",
              template: body?.template,
              text: "Hi Asha, your site visit is on Saturday.",
              status: "sent",
              at: new Date().toISOString(),
            },
          ],
        };
        return json(whatsapp);
      }
      if (url.endsWith(`/leads/${LEAD}/whatsapp`)) return json(whatsapp);
      if (url.endsWith(`/leads/${LEAD}/social`))
        return json({
          configured: true,
          connected: true,
          threads: [
            {
              accountId: ACCOUNT,
              channel: "messenger",
              place: "Messenger · Fictional Homes",
              messages: [
                {
                  id: "m1",
                  direction: "in",
                  kind: "text",
                  text: "Can we visit on Saturday?",
                  status: "received",
                  at: ago(3),
                },
              ],
              windowOpen: true,
              windowClosesAt: new Date(
                Date.now() + 20 * 3600_000,
              ).toISOString(),
              humanAgent: false,
            },
          ],
        });
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
  vi.unstubAllGlobals();
});

const settle = async () => {
  for (let index = 0; index < 6; index += 1)
    await act(async () => {
      await Promise.resolve();
    });
};

const type = async (field: HTMLInputElement, value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });

const view = (channel: "whatsapp" | "messenger") => (
  <ThreadView
    thread={{
      key: `${channel}:${LEAD}`,
      channel,
      leadId: LEAD,
      accountId: null,
      leadName: "Asha Rao",
    }}
    onBack={() => undefined}
    onChanged={() => undefined}
  />
);

it("after 24 hours offers approved WhatsApp templates only, filled in and previewed", async () => {
  await act(async () => root.render(view("whatsapp")));
  await settle();
  expect(host.textContent).toContain("only lets you send an approved template");
  expect(host.querySelector("textarea")).toBeNull();
  const options = [...host.querySelectorAll("option")].map(
    (o) => o.textContent,
  );
  expect(options).toEqual(["Visit reminder (en)"]);
  const send = [...host.querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Fill in 2 parts"),
  )!;
  expect(send.disabled).toBe(true);
  const parts = host.querySelectorAll<HTMLInputElement>(
    "input[aria-label^='Fill in part']",
  );
  await type(parts[0], "Asha");
  await type(parts[1], "Saturday");
  expect(host.textContent).toContain(
    "Hi Asha, your site visit is on Saturday.",
  );
  await act(async () => send.click());
  await settle();
  expect(
    calls.find(
      (call) => call.method === "POST" && call.url.endsWith("/whatsapp"),
    )?.body,
  ).toMatchObject({
    template: "visit_reminder",
    language: "en",
    values: ["Asha", "Saturday"],
  });
});

it("before a yes, notes how they agreed instead", async () => {
  whatsapp = { ...whatsapp, optedIn: false, optInHow: null };
  await act(async () => root.render(view("whatsapp")));
  await settle();
  expect(host.textContent).toContain("agreed to hear from you");
  await type(
    host.querySelector<HTMLInputElement>(
      "input[aria-label='How they agreed']",
    )!,
    "Said yes on the call",
  );
  const agreed = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "They agreed",
  )!;
  await act(async () => agreed.click());
  await settle();
  expect(
    calls.find((call) => call.url.endsWith("/opt-in"))?.body,
  ).toMatchObject({ agreed: true, how: "Said yes on the call" });
  expect(host.querySelector("select")).not.toBeNull();
});

it("shows no AI chip while AI replies are off", async () => {
  await act(async () => root.render(view("messenger")));
  await settle();
  expect(host.textContent).not.toContain("Suggest a reply");
});

it("puts the AI's suggested reply in the box to edit before sending", async () => {
  ai = {
    mode: "suggest",
    channels: ["messenger"],
    ready: true,
    available: true,
    paused: false,
    handoffs: [],
  };
  await act(async () => root.render(view("messenger")));
  await settle();
  const chip = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Suggest a reply",
  )!;
  await act(async () => chip.click());
  await settle();
  expect(host.querySelector<HTMLTextAreaElement>("textarea")!.value).toBe(
    "Hi Asha, Saturday at 11 works. Shall I book it?",
  );
  expect(host.textContent).toContain("read it, change anything, then send");
  // Nothing was sent: the seller sends it themselves.
  expect(
    calls.some(
      (call) => call.method === "POST" && call.url.endsWith("/social"),
    ),
  ).toBe(false);
});
