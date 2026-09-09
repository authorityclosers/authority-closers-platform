// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as platform from "@ac/operations-web/platform-identity";
import { PlatformConsole } from "./platform-console";
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const person = "11111111-1111-4111-8111-111111111111",
  session = "22222222-2222-4222-8222-222222222222",
  tenant = "33333333-3333-4333-8333-333333333333";
const identity: platform.PlatformIdentity = {
  personId: person,
  sessionId: session,
  selectedTenantId: null,
  email: "synthetic@example.test",
  displayName: "Synthetic",
  permissions: ["platform_tenants_read"],
};
const inventory = {
  person_id: person,
  session_id: session,
  next_after_id: null,
  tenants: [
    {
      tenant_id: tenant,
      name: "Example Academy",
      status: "active",
      kind: "academy",
    },
  ],
};
let container: HTMLDivElement, root: Root, disposed: boolean;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  disposed = false;
  vi.spyOn(platform, "loadPlatformIdentity").mockResolvedValue(identity);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(inventory)));
});
afterEach(async () => {
  if (!disposed) await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function mount() {
  await act(async () => root.render(<PlatformConsole />));
}
it("renders a real bounded directory and does not invent privilege controls", async () => {
  await mount();
  expect(container.textContent).toContain("Example Academy");
  expect(container.textContent).toContain("View academies");
  expect(container.textContent).not.toContain("Manage platform access");
  expect(container.querySelector("#admin-content")).not.toBeNull();
  expect(fetch).toHaveBeenCalledWith(
    "/v1/platform/tenants",
    expect.objectContaining({
      cache: "no-store",
      redirect: "error",
      credentials: "same-origin",
    }),
  );
});
it("does not request cross-tenant data for an access-manager-only identity", async () => {
  vi.mocked(platform.loadPlatformIdentity).mockResolvedValue({
    ...identity,
    permissions: ["platform_access_manage"],
  });
  await mount();
  expect(fetch).not.toHaveBeenCalled();
  expect(container.textContent).toContain(
    "does not include the academy directory",
  );
});
it("rejects response from another session", async () => {
  vi.mocked(fetch).mockResolvedValue(
    Response.json({ ...inventory, session_id: person }),
  );
  await mount();
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect(container.textContent).not.toContain("Example Academy");
});
it("does not fetch directory when platform admission cannot be verified", async () => {
  vi.mocked(platform.loadPlatformIdentity).mockResolvedValue(null);
  await mount();
  expect(fetch).not.toHaveBeenCalled();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "could not be verified",
  );
});
it("revalidates permission before pagination and removes stale directory on revocation", async () => {
  vi.mocked(fetch).mockResolvedValue(
    Response.json({ ...inventory, next_after_id: tenant }),
  );
  await mount();
  vi.mocked(platform.loadPlatformIdentity).mockResolvedValue(null);
  await act(async () =>
    [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("Next academies"))!
      .click(),
  );
  expect(fetch).toHaveBeenCalledOnce();
  expect(container.textContent).not.toContain("Example Academy");
});
it("aborts pending page work on unmount", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(
    Response.json({ ...inventory, next_after_id: tenant }),
  );
  await mount();
  let signal: AbortSignal | undefined;
  vi.mocked(platform.loadPlatformIdentity).mockImplementation((options) => {
    signal = options?.signal;
    return new Promise(() => {});
  });
  await act(async () =>
    [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("Next academies"))!
      .click(),
  );
  await act(async () => root.unmount());
  disposed = true;
  expect(signal?.aborted).toBe(true);
});
