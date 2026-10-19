import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { normalizeIntegrations, testWords } from "./integrations-client";
import { IntegrationsPanel } from "./integrations-panel";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const OVERVIEW = {
  schema: "sx-integrations/1",
  api_base: "https://salesxray.example.test/v1/api",
  key_mode: "test",
  scopes: [
    { key: "calls:read", label: "Read calls and their status" },
    { key: "leads:write", label: "Create and update leads" },
  ],
  expiry_days: [30, 90, 365],
  keys: [
    {
      id: "k1",
      name: "Our CRM",
      prefix: "sxk_test_Ab12",
      scopes: ["calls:read"],
      state: "active",
      created_at: "2026-10-19T05:00:00Z",
      created_by_person_id: "p1",
      expires_at: null,
      last_used_at: null,
      revoked_at: null,
    },
  ],
  webhooks_ready: true,
  webhook_menu: {
    events: [
      { key: "analysis.completed", label: "A call's analysis is ready" },
      { key: "lead.created", label: "A lead is added" },
    ],
    facts_profiles: [],
  },
  webhook: null,
};

let root: Root;
let host: HTMLDivElement;
const calls: Array<{ url: string; init?: RequestInit }> = [];

function respond(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

beforeEach(() => {
  calls.length = 0;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.endsWith("/keys") && init?.method === "POST")
        return respond({
          ...OVERVIEW.keys[0],
          id: "k2",
          name: "Partner app",
          prefix: "sxk_test_Zz99",
          key: "sxk_test_Zz99" + "x".repeat(36),
        });
      if (url.endsWith("/webhook") && init?.method === "PUT")
        return respond({
          webhook: {
            id: "w1",
            url: "https://partner.example.test/hooks",
            host: "https://partner.example.test",
            events: ["analysis.completed"],
            facts_profile: null,
            managed_in_app: true,
            secret_hint: "WXYZ",
            rotating: false,
            next_secret_hint: null,
            created_at: "2026-10-19T05:00:00Z",
          },
          secret: "whsec_" + "a".repeat(36) + "WXYZ",
        });
      if (url.endsWith("/webhook/test"))
        return respond({
          delivered: true,
          http_status: 204,
          error_code: null,
          duration_ms: 120,
        });
      if (url.endsWith("/webhook/deliveries"))
        return respond({ deliveries: [] });
      return respond(OVERVIEW);
    }),
  );
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function flush() {
  await act(async () => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
  });
}

function button(name: string) {
  const found = [...document.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(name),
  );
  if (!found) throw new Error(`no button ${name}`);
  return found;
}

it("reads the page defensively", () => {
  const data = normalizeIntegrations({
    ...OVERVIEW,
    keys: [{ state: "odd" }],
    webhook: "x",
  });
  expect(data.keys[0]).toMatchObject({
    state: "active",
    scopes: [],
    prefix: "",
  });
  expect(data.webhook).toBeNull();
  expect(normalizeIntegrations(null).keys).toEqual([]);
  expect(
    testWords({
      delivered: true,
      httpStatus: 204,
      errorCode: null,
      durationMs: 120,
    }),
  ).toBe("Delivered · 204 · 120 ms");
  expect(
    testWords({
      delivered: false,
      httpStatus: null,
      errorCode: "address_refused",
      durationMs: 0,
    }),
  ).toContain("private network");
});

it("lists keys by prefix and shows a new key once", async () => {
  await act(async () => root.render(<IntegrationsPanel />));
  await flush();
  expect(host.textContent).toContain("Our CRM");
  expect(host.textContent).toContain("sxk_test_Ab12…");
  expect(host.textContent).toContain("https://salesxray.example.test/v1/api");

  await act(async () => button("New key").click());
  const name = document.querySelector<HTMLInputElement>(
    "dialog input:not([type])",
  );
  expect(name).not.toBeNull();
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    setter?.call(name, "Partner app");
    name?.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    document
      .querySelector<HTMLInputElement>('dialog input[type="checkbox"]')
      ?.click();
  });
  await act(async () => button("Create key").click());
  await flush();
  const created = calls.find((call) => call.url.endsWith("/keys"));
  expect(JSON.parse(String(created?.init?.body))).toEqual({
    name: "Partner app",
    scopes: ["calls:read"],
    expires_days: 90,
  });
  expect(
    document.querySelector('[data-testid="secret-once"]')?.textContent,
  ).toMatch(/^sxk_test_Zz99/);
  await act(async () => button("I have saved it").click());
  expect(
    document.querySelector('[data-testid="secret-once"]')?.textContent ?? "",
  ).toBe("");
  expect(host.textContent).toContain("Partner app");
});

it("adds the webhook, shows its secret once and sends a test", async () => {
  await act(async () => root.render(<IntegrationsPanel />));
  await flush();
  const url = document.querySelector<HTMLInputElement>('input[type="url"]');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    setter?.call(url, "https://partner.example.test/hooks");
    url?.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Add webhook").click());
  await flush();
  const saved = calls.find((call) => call.init?.method === "PUT");
  expect(JSON.parse(String(saved?.init?.body))).toMatchObject({
    url: "https://partner.example.test/hooks",
    events: ["analysis.completed", "lead.created"],
  });
  expect(
    document.querySelector('[data-testid="secret-once"]')?.textContent,
  ).toMatch(/^whsec_/);
  await act(async () => button("I have saved it").click());
  expect(host.textContent).toContain("whsec_…WXYZ");
  await act(async () => button("Send test event").click());
  await flush();
  expect(host.textContent).toContain("Delivered · 204 · 120 ms");
});

it("sets up the hand-over with a pasted key and the form questions", async () => {
  const puts: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/handover") && init?.method === "PUT") {
        puts.push(JSON.parse(String(init.body)));
        return respond({
          handover: {
            id: "h1",
            url: "https://app.example.test/api/v1/service/customers/handover",
            host: "https://app.example.test",
            lead_fields: { send: ["address"], questions: {}, consents: [] },
            managed_in_app: true,
            key_hint: "abcd",
            created_at: "2026-10-19T05:00:00Z",
          },
        });
      }
      if (url.endsWith("/webhook/deliveries"))
        return respond({ deliveries: [] });
      return respond({
        ...OVERVIEW,
        handover: null,
        handover_menu: {
          path: "/api/v1/service/customers/handover",
          parts: [
            { key: "email", label: "Email" },
            { key: "address", label: "Address" },
          ],
          questions: [{ path: "address.city", part: "address" }],
        },
      });
    }),
  );
  await act(async () => root.render(<IntegrationsPanel />));
  await flush();
  expect(host.textContent).toContain("Hand-over to your customer app");
  const type = async (
    input: HTMLInputElement | null | undefined,
    value: string,
  ) => {
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setter?.call(input, value);
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
  };
  const urls = document.querySelectorAll<HTMLInputElement>('input[type="url"]');
  await type(urls[urls.length - 1], "https://app.example.test");
  await type(
    document.querySelector<HTMLInputElement>('input[type="password"]'),
    "psvc_secret_key",
  );
  const address = [...document.querySelectorAll("label")].find(
    (label) => label.textContent === "Address",
  );
  await act(async () => address?.querySelector("input")?.click());
  const city = [...document.querySelectorAll("label")].find((label) =>
    label.textContent?.startsWith("Form question for City"),
  );
  await type(city?.querySelector("input"), "Which city is the site in?");
  await act(async () => button("Set up hand-over").click());
  await flush();
  expect(puts).toEqual([
    {
      address: "https://app.example.test",
      service_key: "psvc_secret_key",
      lead_fields: {
        send: ["address"],
        questions: { "address.city": "Which city is the site in?" },
        consents: [],
      },
    },
  ]);
  expect(host.textContent).toContain("…abcd");
  expect(host.textContent).not.toContain("psvc_secret_key");
});

it("shows only the parts Settings asks for, and reads integrations only when it needs them", async () => {
  await act(async () =>
    root.render(<IntegrationsPanel parts={["keys", "webhook"]} />),
  );
  await flush();
  const urls = () => calls.map((call) => String(call.url));
  expect(
    urls().some((url) => url.includes("/v1/sales-xray/integrations")),
  ).toBe(true);
  expect(urls().some((url) => url.includes("/v1/lead-desk/"))).toBe(false);

  act(() => root.unmount());
  root = createRoot(host);
  calls.length = 0;
  await act(async () => root.render(<IntegrationsPanel parts={["ai"]} />));
  await flush();
  expect(
    urls().some((url) => url.includes("/v1/sales-xray/integrations")),
  ).toBe(false);
  expect(urls().some((url) => url.includes("/ai-replies"))).toBe(true);
});
