import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  MetaConversions,
  sentLine,
  type Conversions,
  type ConversionEvent,
} from "./meta-conversions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const EVENTS = {
  new: "Lead",
  not_connected: null,
  follow_up: "Follow-up",
  interested: "Interested",
  won: "Won",
  lost: "Lost",
};
const view = (extra: Partial<Conversions> = {}): Conversions => ({
  configured: true,
  connected: true,
  connectionExpiresAt: null,
  dataset: null,
  on: false,
  events: EVENTS,
  testCode: null,
  counts: {},
  lastDeliveredAt: null,
  waitingOn: null,
  recent: [],
  ...extra,
});
const event = (extra: Partial<ConversionEvent> = {}): ConversionEvent => ({
  id: "c1",
  leadId: "l1",
  leadName: "Test Lead 1",
  stage: "won",
  eventName: "Won",
  status: "delivered",
  attempts: 1,
  eventTime: new Date().toISOString(),
  deliveredAt: new Date().toISOString(),
  error: null,
  ...extra,
});

let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string; body?: unknown }[];
let current: Conversions;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  calls = [];
  current = view();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url.endsWith("/conversions") && method === "GET")
        return json(current);
      if (url.endsWith("/datasets") && method === "GET")
        return json({
          adAccounts: [{ id: "act_10000001", name: "Fictional Homes ads" }],
          datasets: [{ id: "777000111", name: "Fictional Homes website" }],
        });
      if (url.endsWith("/datasets") && method === "POST")
        return json({ id: "777000222", name: body.name }, 201);
      if (url.endsWith("/conversions") && method === "PUT") {
        current = view({
          dataset: { id: body.datasetId, name: body.datasetName },
          on: body.on,
          events: body.events,
        });
        return json(current);
      }
      if (url.endsWith("/retry")) {
        current = view({
          dataset: { id: "777000111", name: "Fictional Homes website" },
          on: true,
          recent: [event({ status: "pending" })],
        });
        return json(current);
      }
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

const render = async (returned = false) => {
  await act(async () => root.render(<MetaConversions returned={returned} />));
};
const button = (words: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(words),
  ) as HTMLButtonElement;
const type = async (input: HTMLInputElement, value: string) => {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

it("says in one line what went to Meta", () => {
  expect(sentLine(view())).toBe("No dataset chosen yet");
  const waiting = sentLine(
    view({
      dataset: { id: "1", name: "CRM" },
      on: true,
      settling: 3,
      sendsAt: new Date(Date.now() + 4 * 60_000 - 1000).toISOString(),
      counts: { delivered: 2, pending: 1 },
    }),
  );
  expect(waiting).toContain("3 stages going in about 4 min");
  expect(waiting).toContain("1 waiting to send");
  expect(sentLine(view({ dataset: { id: "1", name: "CRM" }, on: false }))).toBe(
    "Switched off · CRM",
  );
  expect(
    sentLine(
      view({
        dataset: { id: "1", name: "CRM" },
        on: true,
        counts: { delivered: 1 },
      }),
    ),
  ).toBe("Sending to CRM · 1 stage sent this week");
});

it("shows nothing until AC's Meta app is set up", async () => {
  current = view({ configured: false });
  await render();
  expect(host.textContent).toBe("");
});

it("asks to connect again when there is no Meta connection to list datasets", async () => {
  current = view({ connected: false });
  await render();
  expect(host.querySelector("a")?.getAttribute("href")).toBe(
    "/v1/lead-desk/meta/connect",
  );
});

it("goes straight on to the dataset after Continue with Meta and saves the stage names", async () => {
  await render(true);
  expect(host.textContent).toContain(
    "Which Meta dataset gets your lead stages?",
  );
  const radio = host.querySelector('input[type="radio"]') as HTMLInputElement;
  await act(async () => radio.click());
  await type(
    host.querySelector(
      'input[aria-label="Meta event for Won"]',
    ) as HTMLInputElement,
    "Converted",
  );
  await act(async () => button("Send lead stages to Meta").click());
  const put = calls.find((call) => call.method === "PUT");
  expect(put?.body).toMatchObject({
    datasetId: "777000111",
    datasetName: "Fictional Homes website",
    on: true,
    events: { won: "Converted", not_connected: null, new: "Lead" },
    testCode: null,
  });
  expect(host.textContent).toContain(
    "Sending to Fictional Homes website · 0 stages sent this week",
  );
  expect(host.textContent).toContain("set up your sales funnel");
});

it("says what is missing instead of doing nothing", async () => {
  let datasets = [
    { id: "777000111", name: "Fictional Homes website" },
    { id: "777000333", name: "Fictional Homes shop" },
  ];
  const fetcher = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).endsWith("/datasets") && (init?.method ?? "GET") === "GET"
        ? json({ adAccounts: [], datasets })
        : fetcher(input, init),
    ),
  );
  await render(true);
  await act(async () => button("Send lead stages to Meta").click());
  expect(host.textContent).toContain(
    "Pick the dataset that gets your lead stages",
  );
  expect(calls.some((call) => call.method === "PUT")).toBe(false);
  const radio = host.querySelector('input[type="radio"]') as HTMLInputElement;
  await act(async () => radio.click());
  await type(
    host.querySelector(
      'input[aria-label="Meta event for New"]',
    ) as HTMLInputElement,
    " ",
  );
  await act(async () => button("Send lead stages to Meta").click());
  expect(host.textContent).toContain(
    "Give each stage that is switched on a Meta event name",
  );
  expect(calls.some((call) => call.method === "PUT")).toBe(false);
  // With just one dataset, it is picked for you.
  datasets = [{ id: "777000111", name: "Fictional Homes website" }];
  await act(async () => root.unmount());
  root = createRoot(host);
  await render(true);
  const one = host.querySelector('input[type="radio"]') as HTMLInputElement;
  expect(one.checked).toBe(true);
});

it("makes a new dataset in the customer's ad account", async () => {
  await render(true);
  await act(async () => button("Create").click());
  expect(calls).toContainEqual({
    url: "/v1/lead-desk/meta/datasets",
    method: "POST",
    body: { adAccountId: "act_10000001", name: "Sales Xray CRM" },
  });
  const picked = [...host.querySelectorAll('input[type="radio"]')].find(
    (item) => (item as HTMLInputElement).checked,
  );
  expect(picked?.parentElement?.textContent).toContain("Sales Xray CRM");
});

it("lists what went to Meta and sends a refused stage again", async () => {
  current = view({
    dataset: { id: "777000111", name: "Fictional Homes website" },
    on: true,
    counts: { delivered: 1, rejected: 1 },
    waitingOn:
      "Meta ended the connection. Continue with Meta again to keep sending stages.",
    recent: [
      event(),
      event({ id: "c2", status: "rejected", eventName: "Lost" }),
    ],
  });
  await render();
  expect(host.textContent).toContain("Meta ended the connection");
  expect(host.textContent).toContain("Test Lead 1 · Won");
  expect(host.textContent).toContain("Refused");
  await act(async () => button("Try again").click());
  expect(calls).toContainEqual({
    url: "/v1/lead-desk/meta/conversions/c2/retry",
    method: "POST",
    body: undefined,
  });
  expect(host.textContent).toContain("Waiting");
});
