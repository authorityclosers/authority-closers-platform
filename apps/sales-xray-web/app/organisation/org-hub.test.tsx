import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { WorkspaceAccessContext } from "../workspace-access";
import { OrganisationHub } from "./org-hub";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let query = "";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(query),
  usePathname: () => "/organisation",
  useRouter: () => null,
}));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: React.ReactNode }) => (
    <div data-shell="">{children}</div>
  ),
}));
vi.mock("../settings/sections", () => ({
  SettingsSectionView: ({
    id,
    headless,
  }: {
    id: string;
    headless?: boolean;
  }) => <div data-section={id} data-headless={headless ? "" : undefined} />,
}));
vi.mock("./organisation-view", () => ({
  OrganisationView: ({
    sections,
    headless,
  }: {
    sections?: string[];
    headless?: boolean;
  }) => (
    <div
      data-org-view={(sections ?? []).join(",")}
      data-headless={headless ? "" : undefined}
    />
  ),
}));

const TENANT = "00000000-0000-4000-8000-000000000004";

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  query = "";
});

const render = async (
  role: "owner" | "admin" | "member",
  kind: "organisation" | "personal" = "organisation",
) => {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p", sessionId: "s", tenantId: TENANT },
          workspaces: [
            {
              tenant_id: TENANT,
              kind,
              name: "Fictional Homes",
              role,
              sales_xray_enabled: true,
            },
          ],
          retry: () => {},
        }}
      >
        <OrganisationHub />
      </WorkspaceAccessContext.Provider>,
    ),
  );
};

const tabs = () =>
  [
    ...host.querySelectorAll<HTMLAnchorElement>(
      'nav[aria-label="Organisation"] a',
    ),
  ].map((link) => [link.textContent, link.getAttribute("href")]);

// Owner, 23 Oct 2026: "if organisation is clicked there should be clearly
// visible all management options like team, analytics, insights".
it("shows owners every area as a tab, and lists them on Overview", async () => {
  await render("owner");
  expect(host.querySelector("h1")?.textContent).toBe("Fictional Homes");
  expect(tabs()).toEqual([
    ["Overview", "/organisation"],
    ["Team", "/organisation?tab=team"],
    ["Analytics", "/organisation?tab=analytics"],
    ["Insights", "/organisation/insights"],
    ["Leads setup", "/organisation?tab=leads"],
    ["Connections", "/organisation?tab=connections"],
    ["AI on calls", "/organisation?tab=call-ai"],
    ["Company", "/organisation?tab=company"],
    ["Plan & billing", "/settings/plan"],
  ]);
  const listed = [
    ...host.querySelectorAll<HTMLAnchorElement>(
      'ul[aria-label="Organisation"] a',
    ),
  ].map((link) => link.getAttribute("href"));
  expect(listed).toHaveLength(8);
  expect(listed[0]).toBe("/organisation?tab=team");
  expect(
    host.querySelector('nav[aria-label="Organisation"] a[aria-current="page"]')
      ?.textContent,
  ).toBe("Overview");
});

it("shows members the team, the numbers and the company only", async () => {
  await render("member");
  expect(tabs().map(([label]) => label)).toEqual([
    "Overview",
    "Team",
    "Analytics",
    "Company",
  ]);
});

it("opens each tab here, with the hub's header only", async () => {
  query = "tab=team";
  await render("admin");
  expect(
    host.querySelector('[data-section="team"][data-headless]'),
  ).not.toBeNull();
  await act(async () => root.unmount());
  root = createRoot(host);

  query = "tab=analytics";
  await render("admin");
  expect(
    host.querySelector('[data-org-view="overview"][data-headless]'),
  ).not.toBeNull();
  await act(async () => root.unmount());
  root = createRoot(host);

  query = "tab=leads&part=stages";
  await render("owner");
  expect(host.querySelector('[data-section="stages"]')).not.toBeNull();
  expect(host.querySelector('[aria-label="Leads setup"]')).not.toBeNull();
  await act(async () => root.unmount());
  root = createRoot(host);

  // A tab that opens its own page never renders here: Overview instead.
  query = "tab=insights";
  await render("owner");
  expect(
    host.querySelector('nav[aria-label="Organisation"] a[aria-current="page"]')
      ?.textContent,
  ).toBe("Overview");
});

// Owner, 25 Oct 2026: on Leads setup, tapping Stages or Sources left Lead rules
// showing (the part was read from the address only, which a bare replaceState
// doesn't refresh). The same row serves Connections.
it("switches the part on a tap, and keeps it in the address", async () => {
  query = "tab=leads";
  await render("owner");
  const segment = (label: string) =>
    [
      ...host.querySelectorAll<HTMLButtonElement>(
        '[aria-label="Leads setup"] button',
      ),
    ].find((button) => button.textContent === label);
  expect(host.querySelector('[data-section="lead-rules"]')).not.toBeNull();
  await act(async () => segment("Stages")?.click());
  expect(host.querySelector('[data-section="stages"]')).not.toBeNull();
  expect(segment("Stages")?.getAttribute("aria-pressed")).toBe("true");
  expect(new URLSearchParams(window.location.search).get("part")).toBe(
    "stages",
  );
  await act(async () => segment("Sources")?.click());
  expect(host.querySelector('[data-section="sources"]')).not.toBeNull();
  expect(host.querySelector('[data-section="stages"]')).toBeNull();
  await act(async () => root.unmount());
  root = createRoot(host);

  query = "tab=connections";
  await render("owner");
  const connection = [
    ...host.querySelectorAll<HTMLButtonElement>(
      '[aria-label="Connections"] button',
    ),
  ].find((button) => button.textContent === "Developers");
  await act(async () => connection?.click());
  expect(host.querySelector('[data-section="developers"]')).not.toBeNull();
});

it("keeps the organisation page as it was outside an organisation", async () => {
  await render("owner", "personal");
  expect(host.querySelector('nav[aria-label="Organisation"]')).toBeNull();
  expect(host.querySelector('[data-org-view="overview"]')).not.toBeNull();
});
