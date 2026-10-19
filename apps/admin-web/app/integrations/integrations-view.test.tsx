// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { attention, normalizeIntegrations, ordered } from "./integrations-data";
import { IntegrationsView } from "./integrations-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const DATA = normalizeIntegrations({
  schema: "sx-integrations-admin/2",
  environment: "development",
  counts: {
    active_keys: 2,
    keys_unused_30d: 1,
    active_webhooks: 1,
    webhooks_failing: 1,
    connected_apps: 1,
  },
  organisations: [
    {
      id: "org-a",
      name: "Aster Homes",
      kind: "customer",
      keys: [
        {
          id: "key-1",
          name: "CRM sync",
          prefix: "sxk_live_ab12",
          scopes: ["calls:read", "leads:write"],
          state: "active",
          created_at: "2026-10-01T10:00:00+00:00",
          created_by: { person_id: "p1", label: "Asha" },
          last_used_at: null,
          unused_30d: true,
        },
        {
          id: "key-2",
          name: "Old script",
          prefix: "sxk_live_cd34",
          scopes: [],
          state: "revoked",
          revoked_at: "2026-10-10T10:00:00+00:00",
          revoked_by: { person_id: "p2", label: "AC staff" },
        },
      ],
      webhooks: [],
      connections: [
        {
          id: "c1",
          app: "Dialer One",
          scopes: ["calls:read"],
          created_at: "2026-10-05T10:00:00+00:00",
          last_used_at: null,
          revoked_at: null,
        },
      ],
    },
    {
      id: "org-b",
      name: "Birch Realty",
      kind: "company",
      keys: [
        {
          id: "key-3",
          name: "Reports",
          prefix: "sxk_live_ef56",
          scopes: ["reports:read"],
          state: "active",
          last_used_at: "2026-10-19T08:00:00+00:00",
          unused_30d: false,
        },
      ],
      webhooks: [
        {
          id: "hook-1",
          host: "https://hooks.birch.example",
          events: ["call.analysed"],
          status: "active",
          managed_in_app: true,
          last_delivery_at: "2026-10-19T09:00:00+00:00",
          last_status: 500,
          failures_24h: 3,
        },
      ],
      connections: [],
    },
  ],
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  refresh.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("reads rows, flags what needs a look and puts those organisations first", () => {
  const [aster, birch] = DATA.organisations;
  expect(aster.keys[1].revokedBy).toBe("AC staff");
  expect(birch.webhooks[0].lastStatus).toBe("500");
  expect(attention(aster)).toEqual(["1 key unused 30 days"]);
  expect(attention(birch)).toEqual(["1 webhook failing"]);
  // Both need a look: the API's order (by name) holds.
  expect(ordered(DATA.organisations).map((item) => item.name)).toEqual([
    "Aster Homes",
    "Birch Realty",
  ]);
  const calm = { ...birch, webhooks: [] };
  expect(ordered([calm, aster]).map((item) => item.name)).toEqual([
    "Aster Homes",
    "Birch Realty",
  ]);
  expect(normalizeIntegrations({}).organisations).toEqual([]);
});

it("shows counts, keys by prefix, webhooks by host and stop actions only on live rows", async () => {
  await act(async () => root.render(<IntegrationsView data={DATA} />));
  const text = host.textContent ?? "";
  expect(text).toContain("1 unused for 30 days");
  expect(text).toContain("1 failing in the last 24 h");
  expect(text).toContain("sxk_live_ab12…");
  expect(text).toContain("Revoked");
  expect(text).toContain("by AC staff");
  expect(text).toContain("https://hooks.birch.example");
  expect(text).toContain("3 failed in 24 h");
  expect(text).toContain("Dialer One");
  expect(text).toContain("Never used");
  expect(text).toContain("not used yet");
  expect(text).not.toContain("Last used Never");
  expect(text).toContain("Customer");
  expect(text).toContain("Our company");
  const revoke = [...host.querySelectorAll("button")].filter((button) =>
    button.getAttribute("aria-label")?.startsWith("Revoke "),
  );
  // CRM sync and Reports, in table and card: never the revoked key.
  expect(
    revoke.map((button) => button.getAttribute("aria-label")),
  ).not.toContain("Revoke Old script");
  expect(revoke.length).toBeGreaterThan(0);
});

it("asks before revoking, posts once and refreshes the page", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response(JSON.stringify({ id: "key-3", state: "revoked" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<IntegrationsView data={DATA} />));
  const button = host.querySelector<HTMLButtonElement>(
    'tbody button[aria-label="Revoke Reports"]',
  );
  expect(button).not.toBeNull();
  await act(async () => button!.click());
  expect(host.textContent).toContain(
    "Apps using this key stop working at once",
  );
  expect(fetcher).not.toHaveBeenCalled();
  const confirm = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent === "Revoke now",
  );
  await act(async () => confirm!.click());
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [path, init] = fetcher.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(path).toBe("/v1/admin/integrations/keys/key-3/revoke");
  expect(init.method).toBe("POST");
  expect(refresh).toHaveBeenCalled();
  expect(host.querySelector('[role="status"]')?.textContent).toBe("Revoked");
});

it("disconnects an app after asking, and offers it only while connected", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({ id: "c1", revoked_at: "2026-10-19T10:00:00+00:00" }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<IntegrationsView data={DATA} />));
  const disconnect = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Disconnect Dialer One"]',
  );
  await act(async () => disconnect!.click());
  expect(host.textContent).toContain("The app loses access at once");
  const confirm = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent === "Disconnect now",
  );
  await act(async () => confirm!.click());
  const [path] = fetcher.mock.calls[0] as unknown as [string];
  expect(path).toBe("/v1/admin/integrations/connections/c1/revoke");
  expect(refresh).toHaveBeenCalled();

  const gone = normalizeIntegrations({
    organisations: [
      {
        id: "o",
        name: "Gone",
        connections: [
          { id: "c9", app: "Old app", revoked_at: "2026-10-01T00:00:00+00:00" },
        ],
      },
    ],
  });
  await act(async () => root.render(<IntegrationsView data={gone} />));
  expect(
    host.querySelector('button[aria-label="Disconnect Old app"]'),
  ).toBeNull();
  expect(host.textContent).toContain("Disconnected");
});

it("shows the API's refusal and keeps the row", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "That webhook is not here." }), {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
  await act(async () => root.render(<IntegrationsView data={DATA} />));
  const off = host.querySelector<HTMLButtonElement>(
    'tbody button[aria-label="Turn off https://hooks.birch.example"]',
  );
  await act(async () => off!.click());
  const confirm = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent === "Turn off now",
  );
  await act(async () => confirm!.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "That webhook is not here.",
  );
  expect(refresh).not.toHaveBeenCalled();
});

it("explains where integrations come from when there are none", async () => {
  await act(async () =>
    root.render(<IntegrationsView data={normalizeIntegrations({})} />),
  );
  expect(host.textContent).toContain("No integrations yet");
  expect(host.textContent).toContain("Settings → Integrations");
});
