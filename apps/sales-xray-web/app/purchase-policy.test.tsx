// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const { inApp, phoneStatus, setupStatus } = vi.hoisted(() => ({
  inApp: { value: false },
  phoneStatus: vi.fn(),
  setupStatus: vi.fn(),
}));
vi.mock("./in-app-client", () => ({ useInApp: () => inApp.value }));
vi.mock("./leads/native-phone", () => ({ phoneStatus, setupStatus }));

import {
  PLANS_ON_WEB,
  PurchaseGate,
  resetPurchaseStoreForTests,
} from "./purchase-policy";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  resetPurchaseStoreForTests();
  inApp.value = false;
  phoneStatus.mockReset();
  setupStatus.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

async function show() {
  await act(async () =>
    root.render(
      <PurchaseGate fallback={<p>{PLANS_ON_WEB}</p>}>
        <a href="/plans">Choose a plan · ₹2,499</a>
      </PurchaseGate>,
    ),
  );
  await act(async () => {
    for (let n = 0; n < 10; n++) await Promise.resolve();
  });
}

it("sells on the website without asking any phone", async () => {
  await show();
  expect(host.querySelector('a[href="/plans"]')).not.toBeNull();
  expect(phoneStatus).not.toHaveBeenCalled();
});

it("never shows plans, prices or plan links in the Google Play app", async () => {
  inApp.value = true;
  phoneStatus.mockResolvedValue({ store: "play" });
  await show();
  expect(host.querySelector('a[href="/plans"]')).toBeNull();
  expect(host.textContent).toBe(PLANS_ON_WEB);
  expect(host.textContent).not.toMatch(/₹|upgrade|buy/i);
});

it("sells in the download-link app once the phone says so, even from an older status", async () => {
  inApp.value = true;
  phoneStatus.mockResolvedValue({ platform: "android" });
  setupStatus.mockResolvedValue({ store: "direct" });
  await show();
  expect(host.querySelector('a[href="/plans"]')).not.toBeNull();
});

it("keeps purchases hidden in the app while the store is unknown", async () => {
  inApp.value = true;
  phoneStatus.mockResolvedValue(null);
  setupStatus.mockResolvedValue(null);
  await show();
  expect(host.querySelector('a[href="/plans"]')).toBeNull();
  expect(host.textContent).toBe(PLANS_ON_WEB);
});
