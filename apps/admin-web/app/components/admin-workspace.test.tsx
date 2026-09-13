// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";
import { AdminShell } from "./admin-shell";
import { AdminDashboard } from "./admin-dashboard";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const tenantId = "33333333-3333-4333-8333-333333333333";
const account: api.AdminSession = {
  personId: "11111111-1111-4111-8111-111111111111",
  sessionId: "22222222-2222-4222-8222-222222222222",
  tenantId,
  displayName: "Synthetic administrator",
  email: "admin@authorityclosers.com",
  emailVerifiedAt: "2026-09-13T00:00:00Z",
  membershipRole: "admin",
  permissions: ["admin_surface", "learner_diagnose"],
  studioCapabilities: [
    {
      permission: "catalog_read",
      tenant_id: tenantId,
      scope_kind: "tenant",
      program_id: null,
    },
  ],
};
const course = {
  id: "44444444-4444-4444-8444-444444444444",
  slug: "fixture",
  title: "Fixture",
  scope: "tenant" as const,
  access: "selected_tenant" as const,
  version_count: 2,
  draft_count: 1,
  current_published_version_id: "55555555-5555-4555-8555-555555555555",
  latest_version: null,
};
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  localStorage.clear();
  vi.spyOn(api, "loadAdminSession").mockResolvedValue(account);
  vi.spyOn(api, "loadStudioPrograms").mockResolvedValue({
    tenant_id: tenantId,
    programs: [
      course,
      {
        ...course,
        id: "66666666-6666-4666-8666-666666666666",
        access: "global_read_only",
        scope: "global",
        draft_count: 40,
      },
    ],
    truncated: false,
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  localStorage.clear();
});
async function render() {
  await act(async () =>
    root.render(
      <AdminShell
        active="overview"
        eyebrow="Academy"
        title="Overview"
        description="Your workspace"
      >
        <AdminDashboard />
      </AdminShell>,
    ),
  );
}
function button(label: string) {
  const node = host.querySelector<HTMLButtonElement>(
    `button[aria-label="${label}"]`,
  );
  expect(node).not.toBeNull();
  return node!;
}
it("keeps controls available while independent course analytics are loading", async () => {
  vi.mocked(api.loadStudioPrograms).mockReturnValue(new Promise(() => {}));
  await render();
  expect(host.textContent).toContain("Loading your academy");
  expect(host.querySelector('a[href="/people"]')).not.toBeNull();
  expect(host.querySelector('a[href="/sales-xray/review"]')).not.toBeNull();
});
it("counts only academy-owned courses and their actual draft versions", async () => {
  await render();
  expect(
    Array.from(host.querySelectorAll("dl dd")).map((node) => node.textContent),
  ).toEqual(["1", "1", "1"]);
  expect(
    host.querySelector('[role="img"]')?.getAttribute("aria-label"),
  ).toContain("1 of 1");
});
it("rejects a course snapshot from another tenant and retries without invented zero counts", async () => {
  vi.mocked(api.loadStudioPrograms).mockResolvedValueOnce({
    tenant_id: "77777777-7777-4777-8777-777777777777",
    programs: [course],
    truncated: false,
  });
  await render();
  expect(host.textContent).toContain("Course activity could not load");
  expect(host.querySelector("dl")).toBeNull();
  await act(async () =>
    Array.from(host.querySelectorAll("button"))
      .find((node) => node.textContent === "Try again")!
      .click(),
  );
  expect(host.querySelector("dl dd")?.textContent).toBe("1");
});
it("persists navigation collapse across a fresh shell mount", async () => {
  await render();
  await act(async () => button("Collapse Admin navigation").click());
  expect(host.querySelector('[data-collapsed="true"]')).not.toBeNull();
  await act(async () => root.unmount());
  root = createRoot(host);
  await render();
  expect(button("Expand Admin navigation").getAttribute("aria-expanded")).toBe(
    "false",
  );
});
it("opens mobile navigation, makes content inert, and restores it on Escape", async () => {
  await render();
  await act(async () => button("Open Admin navigation").click());
  expect(host.querySelector("main")?.hasAttribute("inert")).toBe(true);
  await act(async () =>
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
  );
  expect(host.querySelector("main")?.hasAttribute("inert")).toBe(false);
  expect(document.activeElement).toBe(button("Open Admin navigation"));
});
it("asks the active editor before logging out and explains a failed sign-out", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("", { status: 503 }));
  let proceed: (() => void) | undefined;
  const guard = (event: Event) => {
    event.preventDefault();
    proceed = (event as CustomEvent<{ proceed: () => void }>).detail.proceed;
  };
  document.addEventListener("ac:studio-before-leave", guard);
  try {
    await render();
    await act(async () => button("Sign out").click());
    expect(fetcher).not.toHaveBeenCalled();
    await act(async () => proceed!());
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/auth/logout",
      expect.objectContaining({ method: "POST" }),
    );
    expect(host.textContent).toContain("Sign-out could not be confirmed");
  } finally {
    document.removeEventListener("ac:studio-before-leave", guard);
  }
});
it("renders public navigation chrome without private dashboard data before session admission", async () => {
  vi.mocked(api.loadAdminSession).mockReturnValue(new Promise(() => {}));
  await render();
  expect(button("Collapse Admin navigation")).not.toBeNull();
  expect(api.loadStudioPrograms).not.toHaveBeenCalled();
  expect(host.textContent).not.toContain("Synthetic administrator");
  expect(host.querySelector('a[href="/sales-xray/review"]')).toBeNull();
});
