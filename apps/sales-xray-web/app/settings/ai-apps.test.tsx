// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => ({
  notify: vi.fn(),
  dismissNotice: vi.fn(),
}));
vi.mock("../notice-center", () => notices);
vi.mock("../sales-xray-workspaces", () => ({
  readSalesXrayWorkspaces: async () => ({
    selected_tenant_id: PERSONAL,
    workspaces: [
      {
        tenant_id: PERSONAL,
        kind: "personal",
        name: "Asha",
        role: null,
        sales_xray_enabled: true,
      },
      {
        tenant_id: HOMES,
        kind: "organisation",
        name: "Fictional Homes",
        role: "member",
        sales_xray_enabled: true,
      },
    ],
  }),
}));

import { AiAppsSection } from "./ai-apps";
import {
  accessWords,
  dayWords,
  parseAiApps,
  usedWords,
} from "./ai-apps-client";

const PERSONAL = "00000000-0000-4000-8000-000000000001";
const HOMES = "00000000-0000-4000-8000-000000000002";
const PULSE = "00000000-0000-4000-8000-0000000000a1";
const HOST = "00000000-0000-4000-8000-0000000000a2";
const GONE = "00000000-0000-4000-8000-0000000000a3";

const row = (over: Record<string, unknown>) => ({
  id: PULSE,
  app: "Pulse",
  client_id: "sxc_fictional",
  scopes: ["calls:read", "leads:read"],
  granted_by_person_id: PERSONAL,
  created_at: "2026-10-20T09:00:00+00:00",
  last_used_at: null,
  revoked_at: null,
  tenant_id: HOMES,
  verified: true,
  maker: "Estate Autopilots",
  ...over,
});

let apps: Record<string, unknown>[];
let fail: boolean;
const calls: { url: string; method: string }[] = [];

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  apps = [
    row({}),
    row({
      id: HOST,
      app: "ChatGPT",
      scopes: ["calls:read", "reports:read", "leads:read", "leads:write"],
      verified: false,
      maker: null,
      tenant_id: PERSONAL,
      last_used_at: new Date().toISOString(),
    }),
    row({ id: GONE, app: "Old app", revoked_at: "2026-10-21T09:00:00+00:00" }),
  ];
  fail = false;
  calls.length = 0;
  notices.notify.mockReset();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      if (fail) return new Response("{}", { status: 503 });
      if (method === "POST") {
        const id = url.split("/")[4];
        apps = apps.map((item) =>
          item.id === id
            ? { ...item, revoked_at: new Date().toISOString() }
            : item,
        );
      }
      return new Response(JSON.stringify({ apps }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const settle = () =>
  act(async () => new Promise((done) => setTimeout(done, 0)));
const button = (label: string) =>
  [...host.querySelectorAll("button")].filter(
    (item) => item.textContent?.trim() === label,
  );

it("lists the live AI apps with what each may do, and the checked mark", async () => {
  await act(async () => root.render(<AiAppsSection />));
  await settle();
  const rows = [
    ...host.querySelectorAll('ul[aria-label="Connected AI apps"] li'),
  ];
  const text = rows.map((item) => item.textContent ?? "");
  expect(text).toHaveLength(2); // the revoked one is history, not shown
  expect(text[0]).toContain("Pulse");
  expect(text[0]).toContain("Reads calls and leads");
  expect(text[0]).toContain("Not used yet");
  expect(text[0]).toContain("Fictional Homes"); // more than one workspace: named
  expect(
    host.querySelector('[aria-label="Checked: made by Estate Autopilots"]'),
  ).not.toBeNull();
  expect(text[1]).toContain("ChatGPT");
  expect(text[1]).toContain("Reads calls, reports and leads · adds leads");
  expect(text[1]).toContain("Used today");
  expect(text[1]).toContain("Personal");
  expect(host.querySelectorAll('[aria-label^="Checked"]')).toHaveLength(1);
});

it("disconnects only after the person confirms", async () => {
  await act(async () => root.render(<AiAppsSection />));
  await settle();
  await act(async () => button("Disconnect")[1].click());
  expect(host.querySelector("dialog")?.textContent).toContain(
    "Disconnect ChatGPT?",
  );
  expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
  const confirm = button("Disconnect").find((item) => item.closest("dialog"));
  await act(async () => confirm?.click());
  await settle();
  expect(calls.filter((call) => call.method === "POST")).toEqual([
    { url: `/v1/me/connected-apps/${HOST}/revoke`, method: "POST" },
  ]);
  const left = host.querySelectorAll('ul[aria-label="Connected AI apps"] li');
  expect(left).toHaveLength(1);
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({
      tone: "success",
      title: "ChatGPT is disconnected",
    }),
  );
});

it("says how to start when nothing is connected", async () => {
  apps = [];
  await act(async () => root.render(<AiAppsSection />));
  await settle();
  expect(host.textContent).toContain("No AI apps connected");
  expect(host.textContent).toContain("Connect ChatGPT or Claude below");
});

it("keeps the outline and a corner card when the list does not load", async () => {
  fail = true;
  await act(async () => root.render(<AiAppsSection />));
  await settle();
  expect(host.querySelector('[aria-busy="true"]')).not.toBeNull();
  expect(host.textContent).not.toContain("No AI apps connected");
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "error", id: "ai-apps" }),
  );
});

it("gives the address to copy and the steps for each app", async () => {
  await act(async () => root.render(<AiAppsSection />));
  await settle();
  expect(host.querySelector("code")?.textContent).toBe(
    `${window.location.origin}/v1/mcp`,
  );
  const copy = host.querySelector('button[aria-label="Copy the address"]');
  expect(copy?.getAttribute("data-variant")).toBe("primary");
  expect(host.querySelector("ol")?.textContent).toContain("Developer mode");
  await act(async () => button("Claude")[0].click());
  expect(host.querySelector("ol")?.textContent).toContain(
    "Add custom connector",
  );
  await act(async () => button("Other apps")[0].click());
  expect(host.querySelector("ol")?.textContent).toContain("remote MCP server");
});

it("reads the server's list and words it plainly", () => {
  expect(parseAiApps({ apps: "no" })).toBeNull();
  expect(parseAiApps({ apps: [{ id: PULSE }] })).toBeNull();
  const parsed = parseAiApps({ apps: [row({ verified: "yes", maker: "" })] });
  expect(parsed?.[0]).toMatchObject({ verified: false, maker: null });
  expect(accessWords(["leads:write"])).toBe("Adds leads");
  expect(accessWords([])).toBe("Knows who you are");
  const now = new Date(2026, 9, 24, 18, 0);
  expect(dayWords(new Date(2026, 9, 24, 16, 30).toISOString(), now)).toMatch(
    /^today 4:30\s?pm$/,
  );
  expect(dayWords(new Date(2026, 9, 23, 9, 0).toISOString(), now)).toBe(
    "yesterday",
  );
  expect(dayWords(new Date(2026, 9, 3, 9, 0).toISOString(), now)).toBe("3 Oct");
  expect(dayWords(new Date(2025, 9, 3, 9, 0).toISOString(), now)).toBe(
    "3 Oct 2025",
  );
  expect(
    usedWords({
      id: PULSE,
      name: "Pulse",
      verified: true,
      maker: null,
      scopes: [],
      workspaceId: HOMES,
      connectedAt: now.toISOString(),
      lastUsedAt: null,
    }),
  ).toBe("Not used yet");
});
