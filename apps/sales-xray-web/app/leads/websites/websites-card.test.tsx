import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { checkAddress, seenSince, WebsitesCard } from "./websites-card";
import {
  emailForWebPerson,
  percent,
  seenAt,
  siteLine,
  websitesFrom,
  type Website,
  type Websites,
} from "./websites-client";

vi.mock("../../notice-center", () => ({ notify: vi.fn() }));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = "2026-10-30T05:12:00.000Z";
const KEY = "sxw_fictionalkeyfictionalkey0001";
const SNIPPET = `<script src="https://sx.example/sx.js" data-key="${KEY}" async></script>`;

const site = (extra: Partial<Website> = {}): Website => ({
  site_id: "s1",
  host: "fictionalclinic.example.com",
  label: "fictionalclinic.example.com",
  status: "active",
  platform: "wordpress",
  added: "seen",
  first_seen_at: NOW,
  last_seen_at: NOW,
  last_page: "https://fictionalclinic.example.com/book",
  last_lead_at: null,
  test: false,
  views: 120,
  forms: 2,
  fills: 4,
  leads: 3,
  blocked: 1,
  rate: 4 / 120,
  pages: [
    {
      path: "/book",
      title: "Book a consultation",
      views: 80,
      forms: 1,
      fills: 4,
      leads: 3,
      blocked: 1,
      rate: 0.05,
      last_day: "2026-10-30",
    },
  ],
  ...extra,
});

const card = (extra: Partial<Websites> = {}): Websites => ({
  on: true,
  key: KEY,
  script_url: "https://sx.example/sx.js",
  snippet: SNIPPET,
  period_days: 30,
  sites: [],
  views: 0,
  leads: 0,
  rate: null,
  now: NOW,
  ...extra,
});

let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string; body: unknown }[];
let answers: Websites[];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  calls = [];
  answers = [card({ key: null, snippet: null })];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({
        url,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      if (url === "/v1/lead-desk/websites/start") answers = [card()];
      if (url.endsWith("/status") && method === "POST")
        answers = [
          card({ sites: [site({ status: "paused" })], now: answers[0].now }),
        ];
      if (url.endsWith("/test")) return json({ lead_id: "l1" }, 201);
      return json(answers.length > 1 ? answers.shift() : answers[0]);
    }),
  );
  vi.stubGlobal("open", vi.fn());
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

const press = async (text: string) => {
  const button = [...document.querySelectorAll<HTMLElement>("button, a")].find(
    (item) => item.textContent?.trim() === text,
  );
  expect(button, text).toBeTruthy();
  await act(async () => button!.click());
  await settle();
};

it("starts with one action, and the sheet waits for the site to say hello", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  await act(async () => root.render(<WebsitesCard />));
  await settle();
  expect(host.textContent).toContain("Not connected");
  expect(host.textContent).toContain("Every form on your site becomes a lead");

  await press("Add website");
  expect(calls).toContainEqual({
    url: "/v1/lead-desk/websites/start",
    method: "POST",
    body: null,
  });
  const sheet = document.querySelector("dialog") as HTMLElement;
  expect(sheet.textContent).toContain("Copy this line");
  expect(sheet.querySelector("pre")?.textContent).toBe(SNIPPET);
  expect(sheet.textContent).toContain("Waiting for your site");
  // The builders' steps: WordPress first, Webflow on a tap.
  expect(sheet.textContent).toContain("WPCode");
  await press("Webflow");
  expect(sheet.textContent).toContain("Head code");

  // The site's first hello arrives: the sheet says so by itself.
  answers = [card({ sites: [site()], views: 1 })];
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3100);
  });
  await settle();
  expect(sheet.textContent).toContain(
    `We saw fictionalclinic.example.com at ${seenAt(NOW, new Date(NOW))}`,
  );
  expect(sheet.textContent).toContain("2 lead forms found");
});

it("opening the site adds it and opens it with the check", async () => {
  answers = [card()];
  await act(async () => root.render(<WebsitesCard />));
  await settle();
  await press("Add website");
  const input = document.querySelector<HTMLInputElement>(
    'input[aria-label="Your site\'s address"]',
  )!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, "www.FictionalClinic.example.com");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await press("Open site");
  expect(window.open).toHaveBeenCalledWith(
    "https://www.fictionalclinic.example.com/?sx_check=1",
    "_blank",
    "noopener",
  );
  expect(calls).toContainEqual({
    url: "/v1/lead-desk/websites",
    method: "POST",
    body: { address: "www.fictionalclinic.example.com" },
  });
});

it("lists each site with its leads and opens its pages, test lead and pause", async () => {
  answers = [card({ sites: [site()], views: 120, leads: 3, rate: 4 / 120 })];
  await act(async () => root.render(<WebsitesCard />));
  await settle();
  expect(host.textContent).toContain("1 live");
  const row = host.querySelector("ul button") as HTMLButtonElement;
  expect(row.textContent).toContain("fictionalclinic.example.com");
  expect(row.textContent).toContain("Live · seen");
  expect(row.textContent).toContain("3 leads");
  expect(row.textContent).toContain("3.3% filled");
  expect(host.textContent).toContain(
    "120 visits · 3 new leads · 3.3% filled a form",
  );

  await act(async () => row.click());
  await settle();
  const sheet = [...document.querySelectorAll("dialog")].find((item) =>
    item.textContent?.includes("Book a consultation"),
  ) as HTMLElement;
  expect(sheet.textContent).toContain("/book · 80 visits · 1 form");
  expect(sheet.textContent).toContain("1 bot fill turned away");
  expect(sheet.textContent).toContain("built with WordPress");

  await press("Send test lead");
  expect(calls).toContainEqual({
    url: "/v1/lead-desk/websites/s1/test",
    method: "POST",
    body: null,
  });
  await press("Pause");
  expect(calls).toContainEqual({
    url: "/v1/lead-desk/websites/s1/status",
    method: "POST",
    body: { status: "paused" },
  });
  expect(sheet.textContent).toContain("Resume");

  await press("Remove this site");
  expect(sheet.textContent).toContain("Leads already here stay.");
  expect(calls.some((call) => call.method === "DELETE")).toBe(false);
});

it("a malformed answer is no answer", () => {
  expect(() => websitesFrom({ sources: [] })).toThrow();
  expect(() => websitesFrom({ ...card(), sites: [{ host: "x" }] })).toThrow();
  expect(websitesFrom(card()).key).toBe(KEY);
});

it("words, numbers and addresses", () => {
  const now = new Date(NOW);
  expect(percent(null)).toBe("–");
  expect(percent(0)).toBe("0%");
  expect(percent(0.0333)).toBe("3.3%");
  expect(percent(0.25)).toBe("25%");
  expect(siteLine(site({ last_seen_at: null }), now)).toBe(
    "Waiting for the first visit",
  );
  expect(siteLine(site({ status: "paused" }), now)).toBe(
    "Paused · its forms add no leads",
  );
  expect(siteLine(site({ forms: 0 }), now)).toMatch(/no lead forms seen yet$/);
  expect(seenAt("2026-10-29T05:12:00.000Z", now)).toMatch(/^Yesterday /);
  expect(seenAt("2026-10-20T05:12:00.000Z", now)).toBe("20 Oct");
  expect(checkAddress("fictionalclinic.example.com/offer")).toBe(
    "https://fictionalclinic.example.com/offer?sx_check=1",
  );
  expect(checkAddress("not a site")).toBeNull();
  expect(checkAddress("")).toBeNull();
  expect(
    seenSince(
      [
        site({ last_seen_at: "2026-10-30T05:00:00.000Z" }),
        site({ site_id: "s2" }),
      ],
      new Date(NOW).getTime() - 60_000,
    )?.site_id,
  ).toBe("s2");
  expect(seenSince([site()], new Date(NOW).getTime() + 1)).toBeUndefined();
  const mail = decodeURIComponent(emailForWebPerson(SNIPPET));
  expect(mail).toContain(SNIPPET);
  expect(mail).toContain("just before </head>");
});
