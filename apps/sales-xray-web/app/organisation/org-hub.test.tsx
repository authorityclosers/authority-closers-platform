import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBrandingForTests } from "../shell/branding-store";
import { WorkspaceAccessContext } from "../workspace-access";
import { OrganisationHub } from "./org-hub";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const replace = vi.hoisted(() => vi.fn());
let query = "";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(query),
  usePathname: () => "/organisation",
  useRouter: () => ({ replace }),
}));
vi.mock("../settings/settings-shell", () => ({
  SettingsOverview: () => <div data-settings-overview="" />,
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
vi.mock("./analytics-view", () => ({
  AnalyticsView: ({ team }: { team: boolean }) => (
    <div data-analytics={team ? "team" : "own"} />
  ),
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
  replace.mockReset();
  window.history.replaceState(null, "", "/");
});

const render = async (
  role: "owner" | "admin" | "manager" | "member" | "viewer",
  kind: "organisation" | "personal" = "organisation",
  tenant = TENANT,
  base?: string,
) => {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p", sessionId: "s", tenantId: tenant },
          workspaces: [
            {
              tenant_id: tenant,
              kind,
              name: "Fictional Homes",
              role,
              sales_xray_enabled: true,
            },
          ],
          retry: () => {},
        }}
      >
        <OrganisationHub base={base} />
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

// Round-2 board 7 (20 Nov 2026): the organisation's settings are one Settings
// again, so the hub's tabs open their Settings sections; Analytics stays here.
it("lists every area, the setup ones as their Settings sections", async () => {
  query = "tab=analytics";
  await render("owner");
  expect(host.querySelector("h1")?.textContent).toBe("Fictional Homes");
  expect(tabs()).toEqual([
    ["Settings", "/settings"],
    ["Team", "/settings/team"],
    ["Analytics", "/organisation?tab=analytics"],
    ["Insights", "/organisation/insights"],
    ["Leads setup", "/settings/lead-rules"],
    ["Connections", "/settings/apps"],
    ["AI on calls", "/settings/call-ai"],
    ["Company", "/settings/organisation"],
    ["Plan & billing", "/settings/plan"],
  ]);
  expect(
    host.querySelector('nav[aria-label="Organisation"] a[aria-current="page"]')
      ?.textContent,
  ).toBe("Analytics");
  expect(replace).not.toHaveBeenCalled();
});

it("shows each role only its areas", async () => {
  query = "tab=analytics";
  await render("member");
  expect(tabs().map(([label]) => label)).toEqual([
    "Settings",
    "Team",
    "Analytics",
    "Company",
  ]);
  await render("viewer");
  expect(tabs().map(([label]) => label)).toEqual([
    "Settings",
    "Team",
    "Analytics",
    "Insights",
    "Company",
  ]);
  await render("manager");
  expect(tabs().map(([label]) => label)).not.toContain("Plan & billing");
});

it("sends every old hub address to its Settings section, its own query kept", async () => {
  const cases: [string, string][] = [
    ["", "/settings"],
    ["tab=overview", "/settings"],
    ["tab=team", "/settings/team"],
    ["tab=leads", "/settings/lead-rules"],
    ["tab=leads&part=rules", "/settings/lead-rules"],
    ["tab=leads&part=stages", "/settings/stages"],
    ["tab=leads&part=sources", "/settings/sources"],
    ["tab=connections", "/settings/apps"],
    ["tab=connections&part=ai-replies", "/settings/ai-replies"],
    ["tab=connections&part=developers", "/settings/developers"],
    ["tab=connections&part=pulse", "/settings/pulse"],
    ["tab=call-ai", "/settings/call-ai"],
    ["tab=company", "/settings/organisation"],
    ["tab=plan", "/settings/plan"],
    ["tab=nonsense", "/settings"],
  ];
  for (const [asked, to] of cases) {
    replace.mockReset();
    query = asked;
    window.history.replaceState(null, "", `/organisation?${asked}`);
    await render("owner");
    expect(replace, asked).toHaveBeenCalledWith(to);
    expect(host.querySelector('nav[aria-label="Organisation"]')).toBeNull();
  }
  // A connect flow coming back keeps its answer.
  replace.mockReset();
  query = "tab=connections&part=apps&connected=meta";
  window.history.replaceState(null, "", `/organisation?${query}`);
  await render("owner");
  expect(replace).toHaveBeenCalledWith("/settings/apps?connected=meta");
});

it("shows the section in place on a review page, for its pictures", async () => {
  query = "tab=leads&part=sources";
  await render("owner", "organisation", TENANT, "/review-fixture/lead-sources");
  expect(replace).not.toHaveBeenCalled();
  expect(host.querySelector('[data-section="sources"]')).not.toBeNull();
  query = "";
  await render("owner", "organisation", TENANT, "/review-fixture/hub");
  expect(host.querySelector("[data-settings-overview]")).not.toBeNull();
});

it("keeps the organisation page as it was outside an organisation", async () => {
  await render("owner", "personal");
  expect(host.querySelector('nav[aria-label="Organisation"]')).toBeNull();
  expect(host.querySelector('[data-org-view="overview"]')).not.toBeNull();
});

// Owner, #25 (26 Oct 2026): the organisation's own logo in its header card.
it("shows the organisation's logo on Analytics as well as other tabs", async () => {
  query = "tab=analytics";
  const logo = "/v1/organisation/logo/00000000-0000-4000-8000-0000000000aa";
  resetBrandingForTests();
  const fetch = vi.fn(async (input: RequestInfo | URL) =>
    String(input).endsWith("/v1/organisation/branding")
      ? new Response(
          JSON.stringify({
            tenant_id: TENANT,
            name: "Fictional Homes",
            logo_url: logo,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        )
      : new Response("{}", { status: 404 }),
  );
  vi.stubGlobal("fetch", fetch);
  try {
    await render("owner");
    await act(async () => {
      for (let n = 0; n < 6; n++) await Promise.resolve();
    });
    const header = host.querySelector("header")!;
    expect(header.querySelector("img")?.getAttribute("src")).toBe(logo);
  } finally {
    vi.unstubAllGlobals();
    resetBrandingForTests();
  }
});

it("keeps sellers on their own activity while viewers can compare team work", async () => {
  query = "tab=analytics";
  await render("member");
  expect(host.querySelector('[data-analytics="own"]')).not.toBeNull();
  await render("viewer");
  expect(host.querySelector('[data-analytics="team"]')).not.toBeNull();
});
