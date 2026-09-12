// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";
import { AdminShell } from "./admin-shell";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const account: api.AdminSession = {
  personId: "11111111-1111-4111-8111-111111111111",
  sessionId: "22222222-2222-4222-8222-222222222222",
  tenantId: "33333333-3333-4333-8333-333333333333",
  displayName: "Synthetic administrator",
  email: "admin@authorityclosers.com",
  emailVerifiedAt: "2026-09-13T00:00:00Z",
  membershipRole: "admin",
  permissions: ["admin_surface"],
  studioCapabilities: [],
};
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.spyOn(api, "loadAdminSession").mockResolvedValue(account);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
async function render() {
  await act(async () =>
    root.render(
      <AdminShell
        active="sales-xray"
        eyebrow="Sales Xray"
        title="Provider controls"
        description="Provider configuration"
      >
        <p>Workspace</p>
      </AdminShell>,
    ),
  );
}
it.each(["owner", "admin"] as const)(
  "shows the current provider entry for the verified control account with %s membership",
  async (membershipRole) => {
    vi.mocked(api.loadAdminSession).mockResolvedValue({
      ...account,
      membershipRole,
    });
    await render();
    const link = host.querySelector(
      'nav[aria-label="Operations"] a[href="/sales-xray"]',
    );
    expect(link?.textContent).toContain("Sales Xray");
    expect(link?.getAttribute("aria-current")).toBe("page");
    expect(
      host.querySelectorAll(
        'nav[aria-label="Operations"] [aria-current="page"]',
      ),
    ).toHaveLength(1);
  },
);
it.each([
  { email: "another@example.test" },
  { emailVerifiedAt: "" },
  { membershipRole: "support" as const },
  { membershipRole: "learner" as const },
  { permissions: [] },
])(
  "hides provider navigation when a required verified-account hint is absent: %j",
  async (change) => {
    vi.mocked(api.loadAdminSession).mockResolvedValue({
      ...account,
      ...change,
    });
    await render();
    expect(host.querySelector('a[href="/sales-xray"]')).toBeNull();
  },
);
it("does not expose provider navigation before session verification", async () => {
  vi.mocked(api.loadAdminSession).mockReturnValue(new Promise(() => {}));
  await render();
  expect(host.querySelector('a[href="/sales-xray"]')).toBeNull();
});
