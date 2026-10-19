import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SlaPanel } from "./sla-panel";
import {
  filled,
  inTimeShare,
  windowLine,
  type WaConversation,
} from "./whatsapp-client";
import { WhatsAppInbox } from "./whatsapp-inbox";
import { WhatsAppSettings } from "./whatsapp-settings";
import { WhatsAppThread } from "./whatsapp-thread";

vi.mock("next/navigation", () => ({
  useSearchParams: () =>
    new URLSearchParams("tab=integrations&whatsapp=connected"),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = new Date("2027-01-15T10:00:00Z");
const TEMPLATE = {
  name: "welcome_lead",
  language: "en",
  category: "UTILITY",
  status: "APPROVED",
  text: "Hi {{1}}, thanks for your enquiry.",
  parts: 1,
};
const NUMBER = {
  id: "n1",
  displayNumber: "+91 80000 00000",
  verifiedName: "Fictional Homes",
  quality: "GREEN",
  autoReplies: {
    firstReply: {
      on: false,
      template: null,
      language: null,
      consentQuestion: null,
    },
    outOfHours: { on: false, text: null },
  },
};
const chat = (extra: Partial<WaConversation> = {}): WaConversation => ({
  configured: true,
  connected: true,
  numbers: [NUMBER],
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
  optedIn: true,
  optInHow: "They messaged you on WhatsApp",
  templates: [TEMPLATE],
  ...extra,
});

let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string; body?: Record<string, unknown> }[];
let current: WaConversation;
let late: {
  leadId: string;
  leadName: string;
  seller: string;
  minutesLate: number;
}[];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  calls = [];
  current = chat();
  late = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url.endsWith("/leads/l1/whatsapp") && method === "GET")
        return json(current);
      if (url.endsWith("/leads/l1/whatsapp") && method === "POST") {
        current = chat({
          messages: [
            ...current.messages,
            {
              id: "m2",
              direction: "out",
              kind: body.template ? "template" : "text",
              text: body.text ?? filled(TEMPLATE.text, body.values),
              status: "sent",
              at: NOW.toISOString(),
              by: "Asha",
            },
          ],
        });
        return json(current);
      }
      if (url.endsWith("/opt-in"))
        return json(
          (current = chat({
            windowOpen: false,
            optedIn: true,
            optInHow: body.how,
          })),
        );
      if (url.endsWith("/whatsapp/status"))
        return json({
          configured: true,
          numbers: [NUMBER],
          templates: [TEMPLATE],
        });
      if (url.endsWith("/whatsapp/inbox"))
        return json([
          {
            leadId: "l1",
            leadName: "Asha Patil",
            lastText: "Hello?",
            lastAt: NOW.toISOString(),
            waiting: true,
            windowOpen: true,
          },
        ]);
      if (url.endsWith("/reports/sla"))
        return json({
          settings: {
            on: false,
            minutes: 15,
            alertManagers: false,
            targets: [5, 10, 15, 30, 60, 120],
          },
          start: "2027-01-09",
          end: "2027-01-15",
          sellers: [
            {
              personId: "p1",
              name: "Asha",
              leads: 4,
              inTime: 3,
              breached: 1,
              waiting: 0,
              medianMinutes: 4,
            },
          ],
          late,
        });
      if (url.endsWith("/sla") && method === "PUT")
        return json({ ...body, targets: [5, 10, 15, 30, 60, 120] });
      return json({}, 404);
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

const button = (words: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(words),
  ) as HTMLButtonElement;
const type = async (
  field: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) => {
  const proto =
    field instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  await act(async () => {
    setter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

it("says how long free replies last, fills templates, and shows the share in time", () => {
  expect(windowLine(chat(), NOW)).toBe(
    "You can reply freely for 3 more hours.",
  );
  expect(
    windowLine(
      chat({
        windowClosesAt: new Date(NOW.getTime() + 20 * 60000).toISOString(),
      }),
      NOW,
    ),
  ).toBe("You can reply freely for 20 more min.");
  expect(
    windowLine(chat({ windowOpen: false, windowClosesAt: null }), NOW),
  ).toContain("send an approved template");
  expect(filled("Hi {{1}}, see you {{2}}", ["Asha"])).toBe(
    "Hi Asha, see you {{2}}",
  );
  expect(
    inTimeShare({ name: "A", leads: 4, inTime: 3, breached: 1, waiting: 0 }),
  ).toBe("75%");
  expect(
    inTimeShare({ name: "A", leads: 1, inTime: 0, breached: 0, waiting: 1 }),
  ).toBe("–");
});

it("replies inside the 24-hour window", async () => {
  await act(async () => root.render(<WhatsAppThread leadId="l1" canSend />));
  expect(host.textContent).toContain("Is the 3 BHK available?");
  expect(host.textContent).toContain("Agreed · They messaged you on WhatsApp");
  await type(
    host.querySelector("textarea") as HTMLTextAreaElement,
    "Yes, it is!",
  );
  await act(async () => button("Send").click());
  const sent = calls.find((call) => call.method === "POST");
  expect(sent?.body).toMatchObject({ text: "Yes, it is!" });
  expect(host.textContent).toContain("Yes, it is!");
  expect(host.textContent).toContain("Sent");
});

it("after 24 hours offers only approved templates, filled in", async () => {
  current = chat({ windowOpen: false, windowClosesAt: null });
  await act(async () => root.render(<WhatsAppThread leadId="l1" canSend />));
  expect(host.querySelector("textarea")).toBeNull();
  expect(button("Send template").disabled).toBe(true);
  await type(
    host.querySelector('input[aria-label="Part 1"]') as HTMLInputElement,
    "Asha",
  );
  expect(host.textContent).toContain("Hi Asha, thanks for your enquiry.");
  await act(async () => button("Send template").click());
  const sent = calls.find((call) => call.method === "POST");
  expect(sent?.body).toMatchObject({
    template: "welcome_lead",
    language: "en",
    values: ["Asha"],
  });
});

it("asks for the person's yes before the first message", async () => {
  current = chat({
    windowOpen: false,
    windowClosesAt: null,
    optedIn: false,
    optInHow: null,
    messages: [],
  });
  await act(async () => root.render(<WhatsAppThread leadId="l1" canSend />));
  expect(host.textContent).toContain("Not agreed yet");
  await type(
    host.querySelector(
      'input[aria-label="How they agreed"]',
    ) as HTMLInputElement,
    "Said yes on the call",
  );
  await act(async () => button("They agreed to WhatsApp").click());
  expect(
    calls.find((call) => call.url.endsWith("/opt-in"))?.body,
  ).toMatchObject({
    agreed: true,
    how: "Said yes on the call",
  });
  expect(host.textContent).toContain("Agreed · Said yes on the call");
});

it("shows nothing on a lead while no WhatsApp number is connected", async () => {
  current = chat({ connected: false, numbers: [] });
  await act(async () => root.render(<WhatsAppThread leadId="l1" canSend />));
  expect(host.textContent).toBe("");
});

it("connects WhatsApp from Settings and lists the number's templates", async () => {
  await act(async () => root.render(<WhatsAppSettings />));
  expect(host.textContent).toContain("WhatsApp is connected.");
  expect(host.textContent).toContain("Fictional Homes");
  expect(host.textContent).toContain(
    "Meta bills your business for its messages",
  );
  const link = host.querySelector("a") as HTMLAnchorElement;
  expect(link.getAttribute("href")).toBe("/v1/lead-desk/whatsapp/start");
  expect(link.textContent).toBe("Add a number");
  expect(host.textContent).toContain("welcome_lead");
  expect(host.textContent).toContain("approved");
});

it("puts conversations waiting for a reply on the desk", async () => {
  const opened: string[] = [];
  await act(async () =>
    root.render(<WhatsAppInbox onOpen={(id) => opened.push(id)} />),
  );
  expect(host.textContent).toContain("1 waiting for a reply");
  await act(async () => button("Asha Patil").click());
  expect(opened).toEqual(["l1"]);
});

it("sets the first-response target and shows each seller's week", async () => {
  await act(async () => root.render(<SlaPanel />));
  expect(host.textContent).toContain("75%");
  expect(host.textContent).toContain("4 min");
  const on = host.querySelector('input[type="checkbox"]') as HTMLInputElement;
  await act(async () => on.click());
  const select = host.querySelector("select") as HTMLSelectElement;
  await act(async () => {
    select.value = "5";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => button("Save").click());
  expect(calls.find((call) => call.method === "PUT")?.body).toEqual({
    on: true,
    minutes: 5,
    alertManagers: false,
  });
  expect(host.textContent).toContain("Target saved: 5 minutes.");
});

it("shows managers who is waiting past the target now and opens that lead", async () => {
  late = [
    { leadId: "l9", leadName: "Kiran Rao", seller: "Asha", minutesLate: 12 },
  ];
  const opened: string[] = [];
  await act(async () =>
    root.render(<SlaPanel onOpen={(leadId) => opened.push(leadId)} />),
  );
  expect(host.textContent).toContain("Waiting past the target now: 1 lead");
  expect(host.textContent).toContain("12 min late");
  await act(async () => button("Kiran Rao").click());
  expect(opened).toEqual(["l9"]);
});
