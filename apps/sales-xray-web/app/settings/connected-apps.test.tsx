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

import { ConnectedApps, appReturnNotice } from "./connected-apps";
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
      app: "lead_stages",
      name: "Lead stages to your ad platforms",
      state: "not_connected",
      words: "Not connected yet.",
      configured: true,
      page: "/leads?tab=stages",
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
    "GET /v1/me/sales-xray-workspaces": () =>
      Response.json({
        selected_tenant_id: "t-sandbox",
        workspaces: [
          {
            tenant_id: "t-sandbox",
            kind: "organisation",
            name: "Brightline Sandbox",
            role: "owner",
            sales_xray_enabled: true,
          },
        ],
      }),
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
  // The same groups as the cards, so nothing moves when they arrive.
  expect(
    host.querySelectorAll('[aria-busy="true"] section > div > div'),
  ).toHaveLength(9);
  await act(async () => release(Response.json(HEALTH)));
  await flush();
  expect(
    [...host.querySelectorAll("article")].map((item) => item.dataset.app),
  ).toEqual([
    "meta_leads",
    "google_ads",
    "lead_stages",
    "whatsapp",
    "phone_calls",
    "ai_replies",
    "sign-in-google",
    "sign-in-facebook",
  ]);
  expect(
    [...host.querySelectorAll("h3")]
      .map((item) => item.textContent)
      .filter((text) =>
        ["Leads and ads", "Messages", "Calls and AI", "Sign-in"].includes(
          text ?? "",
        ),
      ),
  ).toEqual(["Leads and ads", "Messages", "Calls and AI", "Sign-in"]);
  expect(host.textContent).toContain("4 connected");
  expect(host.textContent).toContain("1 needs attention");
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
  // The kit sheet slides away, then closes.
  await act(async () => new Promise((resolve) => setTimeout(resolve, 700)));
  expect(host.querySelector("dialog")?.open ?? false).toBe(false);
  await act(async () => button(card("meta_leads"), "Manage")!.click());
  await flush();
  sheet = host.querySelector("dialog")!;
  // Lead ads are a guided setup; its Pages come from the health read when
  // /meta/status can't be read.
  expect(sheet.textContent).toContain("Brightline Coaching");
  expect(sheet.querySelector('a[href="/leads?tab=sources"]')).not.toBeNull();
  await act(async () => button(sheet, "Switch off")!.click());
  expect(calls.some((call) => call.key.includes("/disconnect"))).toBe(false);
  await act(async () =>
    button(sheet, "Switch off Brightline Coaching?")!.click(),
  );
  await flush();
  expect(calls.filter((call) => call.key.includes("/disconnect"))).toHaveLength(
    1,
  );
  expect(seen.notices).toEqual([
    expect.objectContaining({
      tone: "success",
      title: "Brightline Coaching switched off",
    }),
  ]);
  // The grid reads the apps again.
  expect(
    calls.filter((call) => call.key.endsWith("/integrations/health")),
  ).toHaveLength(2);
});

const PENDING = {
  state: "pending",
  since: "2026-10-19",
  worksNow:
    "Until Meta approves Sales Xray, only Pages run by people added to our Meta app as testers can connect.",
  after: "Once Meta approves it, any business can connect its own Pages here.",
};

it("sets lead ads up step by step, under an honest note on Meta's review", async () => {
  routes["GET /v1/lead-desk/integrations/health"] = () =>
    Response.json({
      ...HEALTH,
      apps: [
        {
          ...HEALTH.apps[0],
          state: "not_connected",
          connections: [],
          lastEvent: null,
          tests: [],
          review: PENDING,
        },
      ],
    });
  routes["GET /v1/lead-desk/meta/status"] = () =>
    Response.json({ configured: true, pages: [] });
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  expect(card("meta_leads").textContent).toContain(
    "Meta approval pending: testers’ Pages only for now",
  );
  // Set up opens the steps first; the trip to Facebook waits for step 1.
  await act(async () => button(card("meta_leads"), "Set up")!.click());
  await flush();
  expect(seen.trips).toEqual([]);
  const sheet = host.querySelector("dialog")!;
  const note = sheet.querySelector('[aria-label="Meta approval"]')!;
  expect(note.textContent).toContain("Waiting for Meta’s approval");
  expect(note.textContent).toContain("Sent for review 19 Oct");
  expect(note.textContent).toContain("testers can connect");
  expect(note.textContent).toContain("any business can connect");
  const steps = [...sheet.querySelectorAll("ol > li")];
  expect(steps.map((step) => step.getAttribute("data-state"))).toEqual([
    "now",
    "later",
    "later",
  ]);
  await act(async () => button(sheet, "Connect Facebook")!.click());
  expect(seen.trips).toEqual(["/v1/lead-desk/meta/connect"]);
});

it("turns a Page on with only the forms ticked, then reads the apps again", async () => {
  routes["GET /v1/lead-desk/integrations/health"] = () =>
    Response.json({
      ...HEALTH,
      apps: [
        {
          ...HEALTH.apps[0],
          state: "not_connected",
          connections: [
            {
              id: "111",
              label: "Brightline Coaching",
              detail: "Forms: all",
              state: "off",
              words: "Switched off.",
            },
          ],
          tests: [],
          review: PENDING,
        },
      ],
    });
  routes["GET /v1/lead-desk/meta/status"] = () =>
    Response.json({
      configured: true,
      pages: [
        {
          pageId: "111",
          name: "Brightline Coaching",
          active: false,
          forms: "all",
          received: 0,
          formsCovered: [],
        },
      ],
    });
  routes["GET /v1/lead-desk/meta/pages/111/forms"] = () =>
    Response.json([
      { id: "f1", name: "Spring intake", status: "ACTIVE" },
      { id: "f2", name: "Old form", status: "ARCHIVED" },
    ]);
  routes["POST /v1/lead-desk/meta/pages/111"] = () =>
    Response.json({ page: {}, imported: 2 });
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  await act(async () => button(card("meta_leads"), "Set up")!.click());
  await flush();
  const sheet = host.querySelector("dialog")!;
  expect(sheet.textContent).toContain("Off: no new leads come in");
  await act(async () => button(sheet, "Turn on")!.click());
  await flush();
  const radios = sheet.querySelectorAll<HTMLInputElement>(
    'input[type="radio"]',
  );
  expect(radios[0].checked).toBe(true);
  await act(async () => radios[1].click());
  const boxes = sheet.querySelectorAll<HTMLInputElement>(
    'input[type="checkbox"]',
  );
  expect(boxes).toHaveLength(2);
  expect(sheet.textContent).toContain("Old form · archived");
  // Nothing ticked yet: it can't be turned on with no forms.
  expect(button(sheet, "Turn on this Page")!.disabled).toBe(true);
  await act(async () => boxes[0].click());
  await act(async () => button(sheet, "Turn on this Page")!.click());
  await flush();
  expect(
    calls.find((call) => call.key === "POST /v1/lead-desk/meta/pages/111")
      ?.body,
  ).toEqual({ forms: ["f1"] });
  expect(seen.notices).toEqual([
    expect.objectContaining({
      tone: "success",
      title: "Brightline Coaching is on",
      message: expect.stringContaining("2 leads from the last week came in"),
    }),
  ]);
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

it("leads an app that needs attention with Reconnect, the one filled button", async () => {
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  const filled = [
    ...host.querySelectorAll<HTMLButtonElement>(
      'article button[data-variant="primary"]',
    ),
  ];
  expect(filled.map((item) => item.textContent)).toEqual(["Reconnect"]);
  expect(filled[0].closest("article")?.getAttribute("data-app")).toBe(
    "whatsapp",
  );
  await act(async () => filled[0].click());
  expect(seen.trips).toEqual(["/v1/lead-desk/whatsapp/start"]);
  // Connect elsewhere is tinted, not filled.
  expect(
    button(card("google_ads"), "Connect")?.getAttribute("data-variant"),
  ).toBe("secondary");
});

it("says what connecting gives instead of sending people to Settings, and names the workspace", async () => {
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  expect(card("google_ads").textContent).toContain(
    "Leads from your Google Ads lead forms arrive in Leads every few minutes.",
  );
  expect(card("google_ads").textContent).not.toContain("Not connected.");
  expect(host.textContent).not.toMatch(/in Settings\./);
  expect(host.textContent).toContain("Brightline Sandbox · 4 connected");
  await act(async () =>
    button(card("whatsapp"), "Send a test message")!.click(),
  );
  expect(host.querySelector("dialog")?.textContent).toContain(
    "Runs in Brightline Sandbox",
  );
});

it("keeps one result at a time, shown once", async () => {
  routes["POST /v1/lead-desk/integrations/phone_calls/test"] = () =>
    Response.json({
      testId: null,
      app: "phone_calls",
      status: "passed",
      words: "Phones fine.",
    });
  routes["POST /v1/lead-desk/integrations/whatsapp/test"] = () =>
    Response.json({
      testId: null,
      app: "whatsapp",
      status: "failed",
      words: "Meta refused.",
    });
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  await act(async () =>
    button(card("phone_calls"), "Check the phones")!.click(),
  );
  await flush();
  expect(card("phone_calls").querySelector('[role="status"]')).not.toBeNull();
  // A test in a sheet shows there only, and the older card result goes.
  await act(async () =>
    button(card("whatsapp"), "Send a test message")!.click(),
  );
  const sheet = host.querySelector("dialog")!;
  const input = sheet.querySelector<HTMLInputElement>('input[type="tel"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "+91 90000 11111");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button(sheet, "Send a test message")!.click());
  await flush();
  expect(host.querySelectorAll('[data-status="failed"]')).toHaveLength(1);
  expect(card("phone_calls").querySelector('[role="status"]')).toBeNull();
  expect(card("whatsapp").querySelector('[role="status"]')).toBeNull();
  // Closed: the result is in its card, once.
  await act(async () =>
    sheet.querySelector<HTMLButtonElement>('[aria-label="Close"]')!.click(),
  );
  await act(async () => new Promise((resolve) => setTimeout(resolve, 700)));
  expect(host.querySelectorAll('[data-status="failed"]')).toHaveLength(1);
  expect(
    card("whatsapp").querySelector('[data-status="failed"]'),
  ).not.toBeNull();
});

it("says once how a connect went on the way back, then drops the query", async () => {
  window.history.replaceState(
    null,
    "",
    "/settings/apps?connected=whatsapp&x=1",
  );
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  expect(seen.notices).toEqual([
    expect.objectContaining({
      tone: "success",
      title: "WhatsApp is connected",
    }),
  ]);
  expect(window.location.search).toBe("?x=1");
  window.history.replaceState(null, "", "/");
});

it("remembers which card a connect started from, for an error that names no app", async () => {
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  await act(async () => button(card("google_ads"), "Connect")!.click());
  expect(window.sessionStorage.getItem("sx.appConnect")).toBe("google_ads");
  expect(
    appReturnNotice("?connect_error=no_accounts", "google_ads"),
  ).toMatchObject({
    tone: "error",
    title: "Couldn’t connect Google Ads",
    message:
      "No accounts were shared. Connect again and choose the accounts to use.",
  });
  expect(
    appReturnNotice("?connect_error=cancelled", "messenger"),
  ).toMatchObject({
    tone: "info",
    title: "Messenger wasn’t connected",
  });
  expect(appReturnNotice("?connect_error=weird", null)).toMatchObject({
    title: "Couldn’t connect the app",
    message: "Try again in a moment.",
  });
  expect(appReturnNotice("", null)).toBeNull();
  window.sessionStorage.clear();
});

it("opens lead stages on their own page, and follows only this app's pages", async () => {
  await act(async () => root.render(<ConnectedApps />));
  await flush();
  const link = card("lead_stages").querySelector("a")!;
  expect(link.getAttribute("href")).toBe("/leads?tab=stages");
  expect(link.textContent).toBe("Set up");
  expect(link.getAttribute("data-variant")).toBe("tinted");
  expect(card("lead_stages").textContent).toContain(
    "Tell Meta and Google which leads became customers",
  );
  expect(button(card("lead_stages"), "Connect")).toBeUndefined();
  for (const page of [
    "https://elsewhere.example/x",
    "//elsewhere.example",
    "/a/../b",
    7,
  ])
    expect(
      parseHealth({ apps: [{ app: "lead_stages", state: "ready", page }] })
        ?.apps[0].page,
    ).toBeNull();
});
