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

it("says how much is set up and links the next step with one button", async () => {
  await act(async () => root.render(inOrg("owner")));
  await act(async () => {
    for (let n = 0; n < 4; n++) await Promise.resolve();
  });
  // sx-redesign pick C (owner, 21 Nov 2026): the ring, the next step, one button.
  expect(host.textContent).toContain("Your company is 3 of 5 set up");
  expect(host.textContent).toContain("Next step");
  expect(host.textContent).toContain("Connect where your leads come from");
  const links = [...host.querySelectorAll("a")].map((link) => [
    link.textContent,
    link.getAttribute("href"),
  ]);
  expect(links).toEqual([["Connect", "/settings/apps"]]);
  expect(
    host.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow"),
  ).toBe("3");
  // The progress shows once: the ring, no second bar.
  expect(host.querySelectorAll('[role="progressbar"]')).toHaveLength(1);
});

it("says so, with no button, once everything is set up", async () => {
  reads.health.mockResolvedValue({
    apps: [{ state: "ready", connections: [] }],
  });
  reads.team.mockResolvedValue({
    people: [{ name: "Asha Fictional", state: "set_up" }],
    missingToday: 0,
  });
  await act(async () => root.render(inOrg("owner")));
  await act(async () => {
    for (let n = 0; n < 4; n++) await Promise.resolve();
  });
  expect(host.textContent).toContain("Fictional Homes is all set up");
  expect(host.querySelector("a")).toBeNull();
});

it("reads the cards' facts with the checklist", async () => {
  const { readSetupFacts } = await import("./setup-checklist");
  const { facts } = await readSetupFacts("t1");
  expect(facts).toEqual({
    companyDone: true,
    people: 4,
    invited: 1,
    appsConnected: 0,
    phonesReady: 1,
    phonesTotal: 2,
  });
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
