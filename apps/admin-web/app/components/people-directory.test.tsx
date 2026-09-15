// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";
import { AdminSessionProvider } from "../lib/admin-session";
import {
  account,
  candidate,
  diagnosis,
  tenantId,
  otherId,
} from "../../test-fixtures/people";
import { PeopleDirectory } from "./people-directory";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
export const directory: api.MemberDirectory = {
  tenant_id: tenantId,
  tenant_name: "Synthetic academy",
  page: 1,
  page_size: 25,
  matching_count: 2,
  summary: { total: 2, active_learners: 1, team: 1, unverified: 0 },
  members: [
    {
      ...candidate,
      email_verified: true,
      account_status: "active",
      joined_at: "2026-09-13T00:00:00Z",
      active_enrollments: 1,
    },
    {
      ...candidate,
      person_id: otherId,
      display_name: "Synthetic Owner",
      membership_role: "owner",
      email_verified: true,
      account_status: "active",
      joined_at: "2026-09-13T00:00:00Z",
      active_enrollments: 0,
    },
  ],
};
const services = {
  directory: vi.fn<typeof api.loadMemberDirectory>(),
  diagnose: vi.fn<typeof api.loadAdminLearnerDiagnosis>(),
};
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.spyOn(api, "loadAdminSession").mockResolvedValue(account);
  services.directory.mockReset().mockResolvedValue(directory);
  services.diagnose.mockReset().mockResolvedValue(diagnosis);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
async function render(key = "people") {
  await act(async () =>
    root.render(
      <AdminSessionProvider refreshKey={key}>
        <PeopleDirectory services={services} />
      </AdminSessionProvider>,
    ),
  );
}
function button(label: string) {
  const found = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) =>
      node.getAttribute("aria-label") === label || node.textContent === label,
  );
  if (!found) throw new Error(`Missing button ${label}`);
  return found;
}
it("loads real member rows on mount and opens learning records without exact lookup", async () => {
  await render();
  expect(services.directory).toHaveBeenCalledTimes(1);
  expect(services.directory.mock.calls[0][0]).toMatchObject({
    tenantId,
    filters: { query: "", page: 1 },
  });
  expect(host.textContent).toContain("Synthetic Owner");
  await act(async () => button("View Synthetic Learner").click());
  expect(document.activeElement?.textContent).toBe("Synthetic Learner");
  await act(async () => button("View learning records").click());
  expect(services.diagnose.mock.calls[0][0]).toMatchObject({
    tenantId,
    personId: candidate.person_id,
    purpose: "learner_support",
  });
  expect(host.textContent).toContain("Practice course");
  await act(async () => button("Close member record").click());
  expect(document.activeElement).toBe(button("View Synthetic Learner"));
});
it("shows owner data without claiming a learner diagnosis or changing roles", async () => {
  await render();
  await act(async () => button("View Synthetic Owner").click());
  expect(host.textContent).toContain("This member’s role remains owner");
  expect(services.diagnose).not.toHaveBeenCalled();
});
it("filters roles and paginates using server counts", async () => {
  services.directory.mockResolvedValue({
    ...directory,
    matching_count: 26,
    summary: { ...directory.summary, total: 26 },
  });
  await render();
  await act(async () => button("Next page").click());
  expect(services.directory.mock.lastCall?.[0].filters?.page).toBe(2);
  await act(async () => {
    const select = host.querySelector("select")!;
    select.value = "owner";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(services.directory.mock.lastCall?.[0].filters).toMatchObject({
    page: 1,
    role: "owner",
  });
});
it("ignores a late response after filtering and allows retry after failure", async () => {
  let resolve!: (value: api.MemberDirectory) => void;
  services.directory.mockReturnValueOnce(
    new Promise((yes) => {
      resolve = yes;
    }),
  );
  await render();
  services.directory.mockRejectedValueOnce(new Error("offline"));
  await act(async () => {
    const select = host.querySelector("select")!;
    select.value = "owner";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => resolve(directory));
  expect(host.textContent).not.toContain("Synthetic Learner");
  expect(host.textContent).toContain("People couldn’t be loaded");
  await act(async () => button("Try again").click());
  expect(host.textContent).toContain("Synthetic Learner");
});
it("removes all private data and invalidates the shell when access is lost", async () => {
  await render();
  await act(async () => button("View Synthetic Learner").click());
  services.directory.mockRejectedValueOnce(
    new api.AdminApiProblem({
      status: 403,
      code: "permission_denied",
      title: "Denied",
      detail: "Denied",
      requestId: null,
    }),
  );
  await act(async () => button("Refresh people").click());
  expect(host.textContent).not.toContain("Synthetic Learner");
  expect(host.textContent).not.toContain("Synthetic Owner");
});
it("abandons unresolved reads after the bounded timeout", async () => {
  vi.useFakeTimers();
  services.directory.mockReturnValue(new Promise(() => {}));
  await render();
  await act(async () => vi.advanceTimersByTime(15001));
  expect(host.textContent).toContain("taking longer than expected");
  expect(services.directory.mock.calls[0][0].signal?.aborted).toBe(true);
});
