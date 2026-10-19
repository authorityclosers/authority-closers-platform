// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const seen = vi.hoisted(() => ({
  notices: [] as { title?: string; tone?: string }[],
  trips: [] as string[],
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));
vi.mock("../notice-center", () => ({
  notify: (notice: { title?: string; tone?: string }) =>
    seen.notices.push(notice),
}));
vi.mock("../sign-in-connect", () => ({
  goToProvider: (url: string) => seen.trips.push(url),
}));
vi.mock("../ui/brand-tile", () => ({ BrandTile: () => null }));
vi.mock("../organisation/integrations/integrations-panel", () => ({
  IntegrationsPanel: ({ parts }: { parts: string[] }) => (
    <p data-testid="integrations-part">{parts.join(",")}</p>
  ),
}));

import { ConnectedApps } from "./connected-apps";
import { parseHealth } from "./connected-apps-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = new Date().toISOString();
const HEALTH = {
  checkedAt: NOW,
  apps: [
    {
      app: "meta_leads",
      name: "Facebook & Instagram lead ads",
      state: "ready",
      words: "1 Page connected. Last lead 5 minutes ago.",
      configured: true,
      connect: { method: "GET", path: "/v1/lead-desk/meta/connect" },
      connections: [
        {
          id: "111",
          label: "Brightline Coaching",
          detail: "Forms: all",
          state: "ready",
          disconnect: {
            method: "POST",
            path: "/v1/lead-desk/meta/pages/111/disconnect",
          },
        },
      ],
      lastEvent: { at: NOW, kind: "lead", words: "New lead" },
      tests: [
        {
          kind: "test_lead",
          label: "Send a test lead",
          needs: ["pageId", "formId"],
        },
      ],
    },
    {
      app: "whatsapp",
      name: "WhatsApp",
      state: "problem",
      words: "1 number connected.",
      configured: true,
      connect: { method: "GET", path: "/v1/lead-desk/whatsapp/start" },
      connections: [
        {
          id: "6b7c0f4e-0000-4000-8000-000000000001",
          label: "+91 90000 00000",
        },
      ],
      lastError: {
        at: NOW,
        words: "Meta says the token expired. Connect again.",
      },
      tests: [
        { kind: "send_test", label: "Send a test message", needs: ["to"] },
      ],
    },
    {
      app: "google_ads",
      name: "Google Ads lead forms",
      state: "not_connected",
      words: "Not connected.",
      configured: true,
      connect: { method: "GET", path: "/v1/lead-desk/google/connect" },
      tests: [],
    },
    {
      app: "phone_calls",
      name: "Phone call logging (Sales Xray app)",
      state: "ready",
      words: "2 phones log calls.",
      configured: true,
      tests: [{ kind: "report", label: "Check the phones", needs: [] }],
    },
    {
      app: "ai_replies",
      name: "AI replies",
      state: "ready",
      words: "On.",
      configured: true,
      tests: [{ kind: "try", label: "Try it", needs: ["message"] }],
    },
    {
      app: "made_up",
      name: "Nope",
      state: "ready",
      words: "",
      configured: true,
    },
  ],
};
const SIGN_IN = {
  methods: [{ kind: "google", removable: true }],
  available: [
    { kind: "google", label: "Google", connected: true },
    { kind: "facebook", label: "Facebook", connected: false },
  ],
};

type Handler = (init?: RequestInit) => Response | Promise<Response>;
let routes: Record<string, Handler>;
let calls: { key: string; body: unknown }[];

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  seen.notices = [];
  seen.trips = [];
  calls = [];
  routes = {
    "GET /v1/lead-desk/integrations/health": () => Response.json(HEALTH),
    "GET /v1/me/sign-in-methods": () => Response.json(SIGN_IN),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`;
      calls.push({
        key,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const handler = routes[key];
      return handler
        ? handler(init)
        : Response.json({ detail: "Not Found" }, { status: 404 });
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
  vi.useRealTimers();
});

async function flush() {
  await act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve();
  });
}
const card = (app: string) =>
  host.querySelector<HTMLElement>(`[data-app="${app}"]`)!;
const button = (scope: ParentNode, text: string) =>
  [...scope.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );

it("draws card outlines first, then one card per app with its status and one main action", async () => {
  let release: (value: Response) => void = () => undefined;
  routes["GET /v1/lead-desk/integrations/health"] = () =>
    new Promise<Response>((resolve) => {
      release = resolve;
    });
  await act(async () => root.render(<ConnectedApps />));
  expect(host.querySelector('[aria-busy="true"]')?.children).toHaveLength(8);
  await act(async () => release(Response.json(HEALTH)));
  await flush();
  expect(
    [...host.querySelectorAll("article")].map((item) => item.dataset.app),
  ).toEqual([
    "meta_leads",
    "whatsapp",
    "google_ads",
    "phone_calls",
    "ai_replies",
    "sign-in-google",
    "sign-in-facebook",
  ]);
  expect(host.textContent).toContain("4 connected");
  expect(host.textContent).toContain("1 need attention");
  expect(card("meta_leads").textContent).toContain("Connected");
  // A problem shows the app's own words about it.
  expect(card("whatsapp").textContent).toContain("Needs attention");
  expect(card("whatsapp").textContent).toContain("Meta says the token expired");
  expect(button(card("meta_leads"), "Manage")).toBeTruthy();
  expect(button(card("google_ads"), "Connect")).toBeTruthy();
  expect(
    card("sign-in-facebook").querySelector("a")?.getAttribute("href"),
  ).toBe("/settings/security");
  expect(card("sign-in-facebook").textContent).toContain("Connect");
});

it("connects an app by a full-page trip to its provider", async () => {
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  await act(async () => button(card("google_ads"), "Connect")!.click());
  expect(seen.trips).toEqual(["/v1/lead-desk/google/connect"]);
});

it("runs a test that needs nothing at once and shows how it went in the card", async () => {
  routes["POST /v1/lead-desk/integrations/phone_calls/test"] = () =>
    Response.json({
      testId: null,
      app: "phone_calls",
      status: "passed",
      words: "2 phones synced in the last hour.",
      steps: [{ label: "Phones report in", state: "done" }],
    });
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  await act(async () =>
    button(card("phone_calls"), "Check the phones")!.click(),
  );
  await flush();
  expect(
    calls.find((call) => call.key.endsWith("/phone_calls/test"))?.body,
  ).toEqual({});
  const outcome = card("phone_calls").querySelector('[role="status"]');
  expect(outcome?.getAttribute("data-status")).toBe("passed");
  expect(outcome?.textContent).toContain("Test passed");
  expect(outcome?.textContent).toContain("2 phones synced in the last hour.");
  expect(outcome?.textContent).toContain("Phones report in");
});

it("follows a test that takes a while every 2 seconds until it finishes", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let polls = 0;
  routes["POST /v1/lead-desk/integrations/phone_calls/test"] = () =>
    Response.json({
      testId: "t-1",
      app: "phone_calls",
      status: "waiting",
      words: "Waiting",
    });
  routes["GET /v1/lead-desk/integrations/tests/t-1"] = () => {
    polls += 1;
    return Response.json(
      polls < 2
        ? {
            testId: "t-1",
            app: "phone_calls",
            status: "waiting",
            words: "Still waiting",
          }
        : {
            testId: "t-1",
            app: "phone_calls",
            status: "failed",
            words: "No phone answered.",
          },
    );
  };
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  await act(async () =>
    button(card("phone_calls"), "Check the phones")!.click(),
  );
  await flush();
  expect(
    card("phone_calls").querySelector('[data-status="waiting"]'),
  ).not.toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(2100));
  await flush();
  await act(async () => vi.advanceTimersByTimeAsync(2100));
  await flush();
  expect(polls).toBe(2);
  const outcome = card("phone_calls").querySelector('[role="status"]');
  expect(outcome?.getAttribute("data-status")).toBe("failed");
  expect(outcome?.textContent).toContain("No phone answered.");
});

it("asks for what a test needs in a sheet, then sends exactly that", async () => {
  routes["POST /v1/lead-desk/integrations/whatsapp/test"] = () =>
    Response.json({
      testId: null,
      app: "whatsapp",
      status: "passed",
      words: "Delivered.",
    });
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  await act(async () =>
    button(card("whatsapp"), "Send a test message")!.click(),
  );
  const sheet = host.querySelector("dialog")!;
  expect(sheet.textContent).toContain("Send a test message · WhatsApp");
  const input = sheet.querySelector<HTMLInputElement>('input[type="tel"]')!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, "+91 90000 11111");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button(sheet, "Send a test message")!.click());
  await flush();
  expect(
    calls.find((call) => call.key.endsWith("/whatsapp/test"))?.body,
  ).toEqual({
    to: "+91 90000 11111",
    numberId: "6b7c0f4e-0000-4000-8000-000000000001",
  });
  expect(sheet.querySelector('[data-status="passed"]')?.textContent).toContain(
    "Delivered.",
  );
});

it("tries AI replies with a sample message and shows the draft it would send", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  routes["POST /v1/lead-desk/ai-replies/try"] = () =>
    Response.json({
      replyId: "r-1",
      status: "queued",
      handoff: false,
      words: "Writing a reply.",
    });
  routes["GET /v1/lead-desk/ai-replies/try/r-1"] = () =>
    Response.json({
      replyId: "r-1",
      status: "drafted",
      handoff: false,
      draft: "Thanks for asking! The next batch starts Monday.",
      words: "This is the reply it would send.",
    });
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  await act(async () => button(card("ai_replies"), "Try it")!.click());
  const sheet = host.querySelector("dialog")!;
  const area = sheet.querySelector("textarea")!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!;
    setter.call(area, "When does it start?");
    area.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button(sheet, "Try it")!.click());
  await flush();
  expect(
    calls.find((call) => call.key.endsWith("/ai-replies/try"))?.body,
  ).toEqual({
    message: "When does it start?",
    channel: "whatsapp",
  });
  await act(async () => vi.advanceTimersByTimeAsync(2100));
  await flush();
  expect(sheet.querySelector("q")?.textContent).toBe(
    "Thanks for asking! The next batch starts Monday.",
  );
});

it("manages an app in a sheet: its connections, disconnect on a second press, and its settings", async () => {
  routes["POST /v1/lead-desk/meta/pages/111/disconnect"] = () =>
    Response.json({ ok: true });
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  await act(async () => button(card("whatsapp"), "Manage")!.click());
  let sheet = host.querySelector("dialog")!;
  expect(
    sheet.querySelector('[data-testid="integrations-part"]')?.textContent,
  ).toBe("whatsapp");
  await act(async () =>
    sheet.querySelector<HTMLButtonElement>('[aria-label="Close"]')!.click(),
  );
  expect(host.querySelector("dialog")).toBeNull();
  await act(async () => button(card("meta_leads"), "Manage")!.click());
  sheet = host.querySelector("dialog")!;
  expect(sheet.textContent).toContain("Brightline Coaching");
  expect(sheet.querySelector('a[href="/leads?tab=sources"]')).not.toBeNull();
  await act(async () => button(sheet, "Disconnect")!.click());
  expect(calls.some((call) => call.key.includes("/disconnect"))).toBe(false);
  await act(async () =>
    button(sheet, "Disconnect Brightline Coaching?")!.click(),
  );
  await flush();
  expect(calls.filter((call) => call.key.includes("/disconnect"))).toHaveLength(
    1,
  );
  expect(seen.notices).toEqual([
    expect.objectContaining({
      tone: "success",
      title: "Brightline Coaching disconnected",
    }),
  ]);
  // The grid reads the apps again.
  expect(
    calls.filter((call) => call.key.endsWith("/integrations/health")),
  ).toHaveLength(2);
});

it("tells members who connects apps instead of an error", async () => {
  routes["GET /v1/lead-desk/integrations/health"] = () =>
    Response.json({ detail: "Owners and admins only." }, { status: 403 });
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  expect(host.textContent).toContain("Owners and admins connect apps");
  expect(seen.notices).toEqual([]);
});

it("says so in a corner card when the apps can't be checked, and tries again", async () => {
  routes["GET /v1/lead-desk/integrations/health"] = () =>
    Response.json({ detail: "Down for a moment." }, { status: 503 });
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  expect(seen.notices).toEqual([
    expect.objectContaining({
      tone: "error",
      title: "Connected apps didn’t load",
    }),
  ]);
  expect(host.textContent).toContain("Your apps couldn’t be checked.");
  routes["GET /v1/lead-desk/integrations/health"] = () => Response.json(HEALTH);
  await act(async () => button(host, "Try again")!.click());
  await flush();
  expect(host.querySelectorAll("article").length).toBeGreaterThan(0);
});

it("reads only known apps and follows only the back end's own routes", () => {
  const parsed = parseHealth({
    apps: [
      {
        app: "meta_leads",
        state: "weird",
        connect: { method: "GET", path: "https://evil.example/connect" },
        connections: [
          {
            id: "1",
            label: "Page",
            disconnect: { method: "POST", path: "/v1/lead-desk/../me" },
          },
        ],
      },
      { app: "nope" },
    ],
  });
  expect(parsed?.apps).toHaveLength(1);
  expect(parsed?.apps[0]).toMatchObject({ state: "problem", connect: null });
  expect(parsed?.apps[0].connections[0].disconnect).toBeNull();
  expect(parseHealth({ apps: "x" })).toBeNull();
});
