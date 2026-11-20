// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const reads = vi.hoisted(() => ({
  company: vi.fn(),
  seats: vi.fn(),
  health: vi.fn(),
  notify: vi.fn(),
  team: vi.fn(),
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));
vi.mock("../organisation/organisation-api", () => ({
  readOrganisationSettings: reads.company,
  readSeats: reads.seats,
}));
vi.mock("./connected-apps-client", () => ({ readHealth: reads.health }));
vi.mock("./notifications-client", () => ({ readNotify: reads.notify }));
vi.mock("../capture-setup/capture-setup-client", () => ({
  readCaptureTeam: reads.team,
}));

import { WorkspaceAccessContext } from "../workspace-access";
import { readSetup, SetupChecklist } from "./setup-checklist";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  reads.company.mockResolvedValue({
    logo_url: "/logo",
    legal_name: "",
    gstin: "",
  });
  reads.seats.mockResolvedValue({ activeMembers: 4, pendingInvites: 1 });
  reads.health.mockResolvedValue({
    apps: [{ state: "not_connected", connections: [] }],
  });
  reads.notify.mockResolvedValue({ working_hours: "10:30–7:00, Mon–Sat" });
  reads.team.mockResolvedValue({
    people: [
      { name: "Rohan Fictional", state: "phone_pending" },
      { name: "Asha Fictional", state: "set_up" },
    ],
    missingToday: 0,
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const inOrg = (role: "owner" | "member") => (
  <WorkspaceAccessContext.Provider
    value={{
      status: "ready",
      authenticated: true,
      context: { personId: "p", sessionId: "s", tenantId: "t1" },
      workspaces: [
        {
          tenant_id: "t1",
          kind: "organisation",
          name: "Fictional Homes",
          role,
          sales_xray_enabled: true,
        },
      ],
      retry: () => {},
    }}
  >
    <SetupChecklist />
  </WorkspaceAccessContext.Provider>
);

it("says how much is set up and links each thing left to its page", async () => {
  await act(async () => root.render(inOrg("owner")));
  await act(async () => {
    for (let n = 0; n < 4; n++) await Promise.resolve();
  });
  expect(host.textContent).toContain("Your organisation is 3 of 5 set up");
  const todos = [...host.querySelectorAll("a")].map((link) => [
    link.textContent,
    link.getAttribute("href"),
  ]);
  expect(todos).toEqual([
    ["Connect where your leads come from", "/settings/apps"],
    ["Turn on phone setup for Rohan Fictional", "/settings/phones"],
  ]);
  expect(host.textContent).toContain("Done: Company, Team, Working hours");
  expect(
    host.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow"),
  ).toBe("3");
});

it("leaves out a line whose read failed, and shows nothing to a seller", async () => {
  reads.health.mockRejectedValue(new Error("offline"));
  const items = await readSetup("t1");
  expect(items.map((item) => item.key)).toEqual([
    "company",
    "team",
    "hours",
    "phones",
  ]);
  reads.company.mockClear();
  await act(async () => root.render(inOrg("member")));
  expect(host.textContent).toBe("");
  expect(reads.company).not.toHaveBeenCalled();
});
