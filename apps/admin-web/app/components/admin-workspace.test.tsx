// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";
import { AdminShell } from "./admin-shell";
import { CourseActivity } from "./admin-dashboard";

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
        <CourseActivity />
      </AdminShell>,
    ),
  );
}
it("says course analytics are loading instead of inventing counts", async () => {
  vi.mocked(api.loadStudioPrograms).mockReturnValue(new Promise(() => {}));
  await render();
  expect(host.textContent).toContain("Loading your academy");
  expect(host.querySelector("dl")).toBeNull();
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
