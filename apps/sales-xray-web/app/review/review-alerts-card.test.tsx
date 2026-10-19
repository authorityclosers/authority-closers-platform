import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ReviewAlertsCard } from "./review-alerts-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const phone = vi.hoisted(() => ({
  inApp: true,
  status: { supported: true, allowed: false, token: null as string | null },
  enabled: {
    supported: true,
    allowed: true,
    token: "fictional-phone-address-0001" as string | null,
  },
  enable: vi.fn(),
  buzz: vi.fn(),
}));

vi.mock("../leads/native-phone", () => ({
  inPhoneApp: () => phone.inApp,
  pushStatus: async () => (phone.inApp ? phone.status : null),
  pushEnable: async (config: unknown) => {
    phone.enable(config);
    return phone.enabled;
  },
  phoneStatus: async () => ({ version: "0.3.test" }),
  buzz: (kind: string) => phone.buzz(kind),
}));

const SETTINGS = {
  schema: "lead-desk/1",
  enabled: true,
  project_id: "fictional-project",
  app_id: "1:000:android:fictional",
  api_key: "fictional-client-key",
  sender_id: "000",
};

let root: Root;
let host: HTMLDivElement;
let push: Record<string, unknown>;
let posts: { url: string; body: Record<string, unknown> }[];

function respond(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

beforeEach(() => {
  phone.inApp = true;
  phone.status = { supported: true, allowed: false, token: null };
  phone.enabled = {
    supported: true,
    allowed: true,
    token: "fictional-phone-address-0001",
  };
  phone.enable.mockReset();
  phone.buzz.mockReset();
  push = SETTINGS;
  posts = [];
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push({
          url,
          body: JSON.parse(String(init.body)) as Record<string, unknown>,
        });
        return respond({ schema: "lead-desk/1", registered: true });
      }
      return respond(push);
    }),
  );
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
  });
}

async function show() {
  await act(async () => root.render(<ReviewAlertsCard />));
  await settle();
}

function turnOn(): HTMLButtonElement | undefined {
  return [...host.querySelectorAll("button")].find(
    (b) => b.textContent === "Turn on alerts",
  );
}

it("turns review alerts on from the review page", async () => {
  await show();
  expect(host.textContent).toContain("Know when a new Report is ready.");
  await act(async () => turnOn()!.click());
  await settle();
  expect(phone.enable).toHaveBeenCalledWith({
    project_id: "fictional-project",
    app_id: "1:000:android:fictional",
    api_key: "fictional-client-key",
    sender_id: "000",
  });
  expect(posts).toEqual([
    {
      url: "/v1/sales-xray/review/devices",
      body: {
        token: "fictional-phone-address-0001",
        platform: "android",
        app_version: "0.3.test",
      },
    },
  ]);
  expect(phone.buzz).toHaveBeenCalledWith("done");
  expect(host.textContent).toBe("");
});

it("says how to allow notifications when the phone says no", async () => {
  phone.enabled = { supported: true, allowed: false, token: null };
  await show();
  await act(async () => turnOn()!.click());
  await settle();
  expect(host.textContent).toContain("Alerts are off.");
  expect(posts).toEqual([]);
});

it("keeps an alerting phone's address current without a card", async () => {
  phone.status = {
    supported: true,
    allowed: true,
    token: "fictional-phone-address-0002",
  };
  await show();
  expect(host.textContent).toBe("");
  expect(posts.map((p) => p.body.token)).toEqual([
    "fictional-phone-address-0002",
  ]);
});

it("shows nothing in a browser", async () => {
  phone.inApp = false;
  await show();
  expect(host.textContent).toBe("");
  expect(fetch).not.toHaveBeenCalled();
});

it("shows nothing to someone who is not a gold reviewer", async () => {
  push = { schema: "lead-desk/1", enabled: false };
  await show();
  expect(host.textContent).toBe("");
  expect(posts).toEqual([]);
});

it("stays away once dismissed", async () => {
  await show();
  const close = host.querySelector<HTMLButtonElement>('[aria-label="Not now"]');
  await act(async () => close!.click());
  expect(host.textContent).toBe("");
  expect(localStorage.getItem("sx-review-alerts-card")).toBe("hidden");
  act(() => root.unmount());
  root = createRoot(host);
  await show();
  expect(host.textContent).toBe("");
});
