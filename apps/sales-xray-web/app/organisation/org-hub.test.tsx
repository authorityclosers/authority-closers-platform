import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBrandingForTests } from "../shell/branding-store";
import { WorkspaceAccessContext } from "../workspace-access";
import { OrganisationHub } from "./org-hub";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const sourceMounted = vi.hoisted(() => vi.fn());
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
vi.mock("./setup/stages", () => ({
  OrganisationStages: () => <div data-section="stages" />,
}));
vi.mock("./setup/rules", () => ({
  OrganisationRules: () => <div data-section="lead-rules" />,
}));
vi.mock("./setup/sources", () => ({
  OrganisationSources: () => {
    useEffect(() => {
      sourceMounted();
    }, []);
    return <div data-section="sources" />;
  },
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
});

const render = async (
  role: "owner" | "admin" | "manager" | "member" | "viewer",
  kind: "organisation" | "personal" = "organisation",
  tenant = TENANT,
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

// Roles B (27 Oct 2026): a Viewer reads the team, and changes nothing.
it("shows a Viewer the team, the numbers and insights, and none of the setup", async () => {
  await render("viewer");
  expect(tabs().map(([label]) => label)).toEqual([
    "Overview",
    "Team",
    "Analytics",
    "Insights",
    "Company",
  ]);
  // A setup tab asked for by address opens Overview instead.
  query = "tab=connections";
  await render("viewer");
  expect(
    host.querySelector('nav[aria-label="Organisation"] a[aria-current="page"]')
      ?.textContent,
  ).toBe("Overview");
});

// Roles B: a Sales manager sets up leads, but billing is for whoever pays and
// API keys and Pulse for those who manage the organisation (roles.ts; the
// servers' guards), so neither shows.
it("shows a Sales manager no Plan & billing, and only the connections they may change", async () => {
  await render("manager");
  expect(tabs().map(([label]) => label)).toEqual([
    "Overview",
    "Team",
    "Analytics",
    "Insights",
    "Leads setup",
    "Connections",
    "AI on calls",
    "Company",
  ]);
  query = "tab=connections";
  await render("manager");
  expect(
    [
      ...host.querySelectorAll<HTMLButtonElement>(
        '[aria-label="Connections"] button',
      ),
    ].map((button) => button.textContent),
  ).toEqual(["Connected apps", "AI replies"]);
  expect(host.querySelector('[data-section="apps"]')).not.toBeNull();
  query = "tab=leads";
  await render("manager");
  expect(
    [
      ...host.querySelectorAll<HTMLButtonElement>(
        '[aria-label="Leads setup"] button',
      ),
    ].map((button) => button.textContent),
  ).toEqual(["Lead rules", "Stages", "Sources"]);
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
  expect(host.querySelector('[data-analytics="team"]')).not.toBeNull();
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

// Owner bug #43 (27 Oct 2026): on a phone the Connections parts wrapped onto
// two lines and pushed the page past the screen, and the open tab sat out of
// sight. Each row scrolls inside itself: the open item comes into view, and the
// row fades at its edge only while more sits past it.
it("brings the open tab and part into view, and fades a row only while more is past its edge", async () => {
  // A 358 px row holding 700 px; Connections and Pulse sit at 600 px.
  const layout: Record<string, (this: HTMLElement) => number> = {
    clientWidth: () => 358,
    scrollWidth: () => 700,
    offsetWidth: () => 100,
    offsetLeft() {
      return ["Connections", "Pulse"].includes(this.textContent ?? "")
        ? 600
        : 0;
    },
  };
  const saved = Object.keys(layout).map(
    (key) =>
      [
        key,
        Object.getOwnPropertyDescriptor(HTMLElement.prototype, key),
      ] as const,
  );
  for (const [key, get] of Object.entries(layout))
    Object.defineProperty(HTMLElement.prototype, key, {
      configurable: true,
      get,
    });
  const frame = () =>
    act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 40));
    });
  const bar = () =>
    host.querySelector<HTMLElement>('[aria-label="Connections"]')!
      .parentElement!;
  try {
    query = "tab=connections&part=pulse";
    await render("owner");
    await frame();
    const nav = host.querySelector<HTMLElement>(
      'nav[aria-label="Organisation"]',
    )!;
    // 600 + 100 - 358, and 32 px to clear the fade.
    expect(nav.scrollLeft).toBe(374);
    expect(nav.getAttribute("data-less")).toBe("");
    expect(bar().scrollLeft).toBe(374);
    // Scrolled to its end: the fade is on the left only.
    expect(bar().getAttribute("data-less")).toBe("");
    expect(bar().hasAttribute("data-more")).toBe(false);
    await act(async () => root.unmount());
    root = createRoot(host);

    query = "tab=connections&part=apps";
    await render("owner");
    await frame();
    // At its start: the fade is on the right only.
    expect(bar().scrollLeft).toBe(0);
    expect(bar().hasAttribute("data-less")).toBe(false);
    expect(bar().getAttribute("data-more")).toBe("");
  } finally {
    for (const [key, descriptor] of saved)
      if (descriptor)
        Object.defineProperty(HTMLElement.prototype, key, descriptor);
      else
        delete (HTMLElement.prototype as unknown as Record<string, unknown>)[
          key
        ];
  }
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

it("starts Sources afresh after switching organisations so old form drafts cannot carry over", async () => {
  sourceMounted.mockClear();
  query = "tab=leads&part=sources";
  await render("owner");
  expect(sourceMounted).toHaveBeenCalledTimes(1);
  await render("owner", "organisation", "00000000-0000-4000-8000-000000000099");
  expect(sourceMounted).toHaveBeenCalledTimes(2);
});
