// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const { inApp, iPhoneApp, phoneStatus, setupStatus } = vi.hoisted(() => ({
  inApp: { value: false },
  iPhoneApp: { value: false },
  phoneStatus: vi.fn(),
  setupStatus: vi.fn(),
}));
vi.mock("./in-app-client", () => ({
  useInApp: () => inApp.value,
  useIPhoneApp: () => iPhoneApp.value,
}));
vi.mock("./leads/native-phone", () => ({ phoneStatus, setupStatus }));

import {
  PLANS_ON_WEB,
  PurchaseGate,
  resetPurchaseStoreForTests,
  usePlansOnWebLine,
  YOUR_PLANS_ON_WEB,
} from "./purchase-policy";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  resetPurchaseStoreForTests();
  inApp.value = false;
  iPhoneApp.value = false;
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

// App Store 3.1.1 (iOS QA, 18 Nov 2026): the iPhone app never sells, even if
// a status ever says "direct"; Android's download-link app still does.
it("never shows plans, prices or plan links in the iPhone app", async () => {
  inApp.value = true;
  iPhoneApp.value = true;
  phoneStatus.mockResolvedValue({ store: "direct" });
  setupStatus.mockResolvedValue({ store: "direct" });
  await show();
  expect(host.querySelector('a[href="/plans"]')).toBeNull();
  expect(host.textContent).toBe(PLANS_ON_WEB);
  expect(host.textContent).not.toMatch(/₹|upgrade|buy|pricing/i);
});

function PlansLine() {
  return <p>{usePlansOnWebLine()}</p>;
}

it.each([
  ["owner", YOUR_PLANS_ON_WEB],
  ["member", PLANS_ON_WEB],
] as const)(
  "tells an organisation %s the line that fits who pays",
  async (role, line) => {
    await act(async () =>
      root.render(
        <WorkspaceAccessProvider
          value={{
            status: "ready",
            authenticated: true,
            retry: () => {},
            context: { personId: "p", sessionId: "s", tenantId: "org" },
            workspaces: [
              {
                tenant_id: "org",
                kind: "organisation",
                name: "Brightline",
                role,
                sales_xray_enabled: true,
              },
            ],
          }}
        >
          <PlansLine />
        </WorkspaceAccessProvider>,
      ),
    );
    expect(host.textContent).toBe(line);
  },
);

// App Store 3.1.1/3.1.3 (orchestrator, 18 Nov 2026): the iPhone app never says
// plans are managed on the web, for an owner or a member; Android and the website do.
it.each(["owner", "member"] as const)(
  "tells an organisation %s nothing about plans on the web in the iPhone app",
  async (role) => {
    inApp.value = true;
    iPhoneApp.value = true;
    await act(async () =>
      root.render(
        <WorkspaceAccessProvider
          value={{
            status: "ready",
            authenticated: true,
            retry: () => {},
            context: { personId: "p", sessionId: "s", tenantId: "org" },
            workspaces: [
              {
                tenant_id: "org",
                kind: "organisation",
                name: "Brightline",
                role,
                sales_xray_enabled: true,
              },
            ],
          }}
        >
          <PlansLine />
        </WorkspaceAccessProvider>,
      ),
    );
    expect(host.textContent).toBe("");
    expect(host.textContent).not.toMatch(/web|plan|upgrade|buy/i);
  },
);

it("keeps the plans-on-web line in the Android app", async () => {
  inApp.value = true;
  await act(async () => root.render(<PlansLine />));
  expect(host.textContent).toMatch(/on the web\.$/);
});
