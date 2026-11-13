import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AlertsCard } from "./alerts-card";
import { ALERTS_PHONE_ON } from "../settings/notifications-client";

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

vi.mock("./native-phone", () => ({
  inPhoneApp: () => phone.inApp,
  pushStatus: async () => (phone.inApp ? phone.status : null),
  pushEnable: async (config: unknown) => {
    phone.enable(config);
    return phone.enabled;
  },
  phoneStatus: async () => ({ version: "1.0.test" }),
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
let posts: { url: string; body: Record<string, unknown> }[];
let signals: number;
const count = () => (signals += 1);

function respond(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
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
  posts = [];
  signals = 0;
  window.addEventListener(ALERTS_PHONE_ON, count);
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
      return respond(SETTINGS);
    }),
  );
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.removeEventListener(ALERTS_PHONE_ON, count);
  vi.unstubAllGlobals();
});

async function show() {
  await act(async () => root.render(<AlertsCard />));
  await act(async () => {
    for (let i = 0; i < 16; i += 1) await Promise.resolve();
  });
}

it("starts alerts without a card once phone setup has allowed notifications", async () => {
  // Redmi QA on the owner's production build, 13 Nov 2026: Android allowed
  // notifications, but only this card's button started alerts, so the phone
  // never registered and no new-lead alert reached it.
  phone.status = { supported: true, allowed: true, token: null };
  await show();
  expect(host.textContent).toBe("");
  expect(phone.enable).toHaveBeenCalledWith({
    project_id: "fictional-project",
    app_id: "1:000:android:fictional",
    api_key: "fictional-client-key",
    sender_id: "000",
  });
  expect(posts).toEqual([
    {
      url: "/v1/lead-desk/devices",
      body: {
        token: "fictional-phone-address-0001",
        platform: "android",
        app_version: "1.0.test",
      },
    },
  ]);
  // Settings' Phone & alerts reads its phones again.
  expect(signals).toBe(1);
});

it("keeps an alerting phone's address current without asking again", async () => {
  phone.status = {
    supported: true,
    allowed: true,
    token: "fictional-phone-address-0002",
  };
  await show();
  expect(host.textContent).toBe("");
  expect(phone.enable).not.toHaveBeenCalled();
  expect(posts.map((post) => post.body.token)).toEqual([
    "fictional-phone-address-0002",
  ]);
});

it("offers the card while the phone doesn't allow notifications, and turns alerts on", async () => {
  await show();
  expect(host.textContent).toContain("Know the moment a lead comes in.");
  expect(phone.enable).not.toHaveBeenCalled();
  const turnOn = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Turn on alerts",
  );
  await act(async () => turnOn!.click());
  await act(async () => {
    for (let i = 0; i < 16; i += 1) await Promise.resolve();
  });
  expect(posts.map((post) => post.body.token)).toEqual([
    "fictional-phone-address-0001",
  ]);
  expect(phone.buzz).toHaveBeenCalledWith("done");
  expect(signals).toBe(1);
  expect(host.textContent).toBe("");
});

it("offers the card when allowed notifications still give no address", async () => {
  phone.status = { supported: true, allowed: true, token: null };
  phone.enabled = { supported: true, allowed: true, token: null };
  await show();
  expect(host.textContent).toContain("Know the moment a lead comes in.");
  expect(posts).toEqual([]);
});

it("shows nothing and sends nothing in a browser", async () => {
  phone.inApp = false;
  await show();
  expect(host.textContent).toBe("");
  expect(fetch).not.toHaveBeenCalled();
});
