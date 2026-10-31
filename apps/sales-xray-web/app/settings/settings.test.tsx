// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PLAY_OPT_IN_URL } from "../apps/play";
import { ANDROID_APK_URL } from "../apps/release";

const nav = vi.hoisted(() => ({ pathname: "/settings", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ replace: nav.replace, push: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  notFound: () => {
    throw new Error("not found");
  },
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));
const seen = vi.hoisted(() => ({
  account: [] as unknown[],
  organisation: [] as unknown[],
}));
vi.mock("../account-settings", () => ({
  AccountSettings: (props: unknown) => {
    seen.account.push(props);
    return <p>account panes</p>;
  },
}));
vi.mock("../organisation/organisation-view", () => ({
  OrganisationView: (props: unknown) => {
    seen.organisation.push(props);
    return <p>organisation panes</p>;
  },
}));
vi.mock("../leads/alerts-card", () => ({ AlertsCard: () => null }));
vi.mock("./profile-details", () => ({ ProfileDetailsPanel: () => null }));
vi.mock("./developers", () => ({
  DevelopersSection: () => <p data-testid="developers">developers</p>,
}));
vi.mock("./connected-apps", () => ({
  ConnectedApps: () => <p data-testid="connected-apps">apps grid</p>,
}));
vi.mock("./ai-apps", () => ({
  AiAppsSection: () => <p data-testid="ai-apps">ai apps</p>,
}));

import { WorkspaceAccessContext } from "../workspace-access";
import { SettingsSectionView } from "./sections";
import { SettingsSkeleton } from "./settings-skeleton";
import { AccountRedirect } from "./account-redirect";
import SettingsPage from "./page";
import { SettingsShell, currentSection } from "./settings-shell";
import {
  SETTINGS_LINKS,
  SETTINGS_SECTIONS,
  hubAddress,
  accountRedirect,
  isSettingsSection,
  settingsPath,
} from "./settings-sections";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  nav.replace.mockReset();
  seen.account = [];
  seen.organisation = [];
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("maps every section, and the old account sections, to an address of its own", () => {
  expect(SETTINGS_SECTIONS.map((item) => item.id)).toEqual([
    "profile",
    "selling",
    "security",
    "ai-apps",
    "plan",
    "privacy",
    "organisation",
    "team",
    "lead-rules",
    "stages",
    "call-ai",
    "sources",
    "apps",
    "ai-replies",
    "developers",
    "pulse",
    "notifications",
    "devices",
    "help",
  ]);
  // Organisation → Connections → Pulse (25 Oct 2026) lives in the organisation hub.
  expect(isSettingsSection("pulse")).toBe(true);
  expect(settingsPath("team")).toBe("/settings/team");
  // Leads' own settings (approved map, slice 5, 22 Oct 2026).
  expect(settingsPath("stages")).toBe("/settings/stages");
  expect(settingsPath("lead-rules")).toBe("/settings/lead-rules");
  expect(settingsPath("sources")).toBe("/settings/sources");
  expect(settingsPath("billing")).toBe("/settings/plan");
  expect(settingsPath("usage")).toBe("/settings/plan");
  expect(settingsPath("general")).toBe("/settings/profile");
  expect(settingsPath("SECURITY")).toBe("/settings/security");
  expect(settingsPath("nonsense")).toBe("/settings");
  expect(settingsPath()).toBe("/settings");
  expect(accountRedirect("#billing", "")).toBe("/settings/plan");
  expect(accountRedirect("#settings/help", "")).toBe("/settings/help");
  expect(accountRedirect("", "?section=security")).toBe("/settings/security");
  expect(accountRedirect("", "")).toBe("/settings");
  expect(isSettingsSection("ai-replies")).toBe(true);
  expect(isSettingsSection("billing")).toBe(false);
  expect(currentSection("/settings/team")).toBe("team");
  expect(currentSection("/settings")).toBeNull();
});

it("lists every section in groups on the Settings page", async () => {
  nav.pathname = "/settings";
  await act(async () =>
    root.render(<SettingsShell>{<SettingsPage />}</SettingsShell>),
  );
  const links = [
    ...host.querySelectorAll<HTMLAnchorElement>("a[href^='/settings/']"),
  ];
  // Once in the side list (computers), once as cards (the page itself);
  // the organisation's sections live in its hub (owner, 23 Oct 2026).
  expect(new Set(links.map((link) => link.getAttribute("href")))).toEqual(
    new Set(
      // Privacy and Apps & devices open inside Phone & alerts (owner, 24 Oct 2026).
      SETTINGS_SECTIONS.filter(
        (item) => !hubAddress(item.id) && !item.within,
      ).map((item) => `/settings/${item.id}`),
    ),
  );
  expect(
    host.querySelector('nav[aria-label="Settings sections"]'),
  ).not.toBeNull();
  expect(host.textContent).toContain("Organisation");
  expect(host.textContent).toContain("Google, Facebook and Apple sign-in");
  expect(host.querySelector("a[aria-current='page']")).toBeNull();
});

it("shows one section with its title, the way back, and the side list lit", async () => {
  nav.pathname = "/settings/selling";
  await act(async () =>
    root.render(
      <SettingsShell>
        <p>selling section</p>
      </SettingsShell>,
    ),
  );
  expect(host.querySelector("h1")?.textContent).toBe("Selling");
  expect(host.querySelector('a[href="/settings"]')?.textContent).toContain(
    "Settings",
  );
  expect(
    host.querySelector("a[aria-current='page']")?.getAttribute("href"),
  ).toBe("/settings/selling");
  expect(host.textContent).toContain("selling section");
});

it("builds each section from the existing screens, with only its own parts", async () => {
  const render = async (id: Parameters<typeof SettingsSectionView>[0]["id"]) =>
    act(async () => root.render(<SettingsSectionView id={id} />));
  await render("profile");
  await render("plan");
  await render("security");
  expect(
    seen.account.map((props) => (props as { only: string[] }).only),
  ).toEqual([["profile", "general"], ["usage", "billing"], ["security"]]);
  await render("organisation");
  await render("team");
  await render("apps");
  await render("ai-replies");
  const organisation = seen.organisation as {
    embedded: boolean;
    sections: string[];
    integrationParts?: string[];
  }[];
  expect(organisation.every((props) => props.embedded)).toBe(true);
  expect(
    organisation.map((props) => [props.sections, props.integrationParts]),
  ).toEqual([
    // The company's details; the overview stays at /organisation.
    [["company"], undefined],
    [["members"], undefined],
    [["integrations"], ["ai"]],
  ]);
  // Developers: the docs first, keys, Try it, your AI assistant, the webhook.
  await render("developers");
  expect(host.querySelector('[data-testid="developers"]')).not.toBeNull();
  // Connected apps is one grid of app cards of its own.
  await render("apps");
  expect(host.querySelector('[data-testid="connected-apps"]')).not.toBeNull();
  // Phone & alerts: your own switches on one screen; Apps & devices opens it too.
  await render("devices");
  // Google Play first; the app file stays under it (24 Oct 2026).
  expect(host.querySelector(`a[href="${PLAY_OPT_IN_URL}"]`)).not.toBeNull();
  expect(host.querySelector(`a[href="${ANDROID_APK_URL}"]`)).not.toBeNull();
  expect(host.textContent).toContain("Usage analytics");
  await render("notifications");
  expect(host.textContent).toContain("Usage analytics");
  expect(host.textContent).toContain("Product updates show under the bell");
});

it("sends an old /account address to its section", async () => {
  window.history.replaceState(null, "", "/account#billing");
  await act(async () => root.render(<AccountRedirect />));
  expect(nav.replace).toHaveBeenCalledWith("/settings/plan");
  expect(host.querySelector('[role="status"]')).not.toBeNull();
  window.history.replaceState(null, "", "/");
});

it("keeps the Settings frame while the session is checked", async () => {
  nav.pathname = "/settings/notifications";
  await act(async () => root.render(<SettingsSkeleton />));
  const status = host.querySelector(
    '[role="status"][aria-label="Loading settings"]',
  );
  expect(status?.getAttribute("aria-busy")).toBe("true");
  expect(host.querySelector("h1")?.textContent).toBe("Phone & alerts");
  expect(
    host.querySelector("a[aria-current='page']")?.getAttribute("href"),
  ).toBe("/settings/notifications");
  // The overview needs no data, so it is the page itself.
  nav.pathname = "/settings";
  await act(async () => root.render(<SettingsSkeleton />));
  expect(host.querySelector("h1")?.textContent).toBe("Settings");
  expect(host.querySelectorAll("a[data-variant='list']")).toHaveLength(
    SETTINGS_SECTIONS.filter((item) => !hubAddress(item.id) && !item.within)
      .length + SETTINGS_LINKS.length,
  );
});

// Owner, 23 Oct 2026: the organisation's settings live in its hub, so the
// Organisation group is one way there.
it("sends the organisation's settings to its hub", async () => {
  nav.pathname = "/settings";
  await act(async () =>
    root.render(<SettingsShell>{<SettingsPage />}</SettingsShell>),
  );
  expect(host.querySelector('a[href="/settings/stages"]')).toBeNull();
  const hub = [
    ...host.querySelectorAll<HTMLAnchorElement>('a[href="/organisation"]'),
  ];
  // Once in the side list, once as a card on the overview.
  expect(hub).toHaveLength(2);
  expect(
    hub.every((link) => link.closest('section[aria-label="Organisation"]')),
  ).toBe(true);
  expect(hubAddress("stages")).toBe("/organisation/stages");
  expect(hubAddress("profile")).toBeNull();
});

// Billing belongs to whoever pays (roles.ts "billing.view"): a Seller of an
// organisation finds no Plan & usage, and its address says so in one calm
// line, with no price and no top-up; a personal workspace keeps its plan.
const inWorkspace = (
  node: React.ReactNode,
  kind: "organisation" | "personal",
  role: "owner" | "member" | null,
) => (
  <WorkspaceAccessContext.Provider
    value={{
      status: "ready",
      authenticated: true,
      context: { personId: "person-1", sessionId: "session-1", tenantId: "t1" },
      workspaces: [
        {
          tenant_id: "t1",
          kind,
          name: "Fictional Homes",
          role,
          sales_xray_enabled: true,
        },
      ],
      retry: () => {},
    }}
  >
    {node}
  </WorkspaceAccessContext.Provider>
);

it("leaves Plan & usage out for a Seller, and says who sees billing at its address", async () => {
  nav.pathname = "/settings";
  await act(async () =>
    root.render(
      inWorkspace(
        <SettingsShell>{<SettingsPage />}</SettingsShell>,
        "organisation",
        "member",
      ),
    ),
  );
  expect(host.querySelector('a[href="/settings/plan"]')).toBeNull();
  expect(host.textContent).not.toContain("Plan & usage");
  expect(host.querySelector('a[href="/settings/profile"]')).not.toBeNull();
  await act(async () =>
    root.render(
      inWorkspace(<SettingsSectionView id="plan" />, "organisation", "member"),
    ),
  );
  expect(host.textContent).toBe(
    "Only your organisation's owner can see billing.",
  );
  expect(seen.account).toEqual([]);
  expect(host.querySelector("a, button")).toBeNull();
  // Its page keeps the name but not "Your plan and invoices".
  nav.pathname = "/settings/plan";
  await act(async () =>
    root.render(
      inWorkspace(
        <SettingsShell>
          <SettingsSectionView id="plan" />
        </SettingsShell>,
        "organisation",
        "member",
      ),
    ),
  );
  expect(host.querySelector("h1")?.textContent).toBe("Plan & usage");
  expect(host.textContent).not.toContain("Your plan and invoices");
  expect(host.textContent).toContain(
    "Only your organisation's owner can see billing.",
  );
});

it("keeps Plan & usage for an organisation's owner and in a personal workspace", async () => {
  for (const [kind, role] of [
    ["organisation", "owner"],
    ["personal", null],
  ] as const) {
    seen.account = [];
    nav.pathname = "/settings";
    await act(async () =>
      root.render(
        inWorkspace(
          <SettingsShell>{<SettingsPage />}</SettingsShell>,
          kind,
          role,
        ),
      ),
    );
    expect(host.querySelector('a[href="/settings/plan"]')).not.toBeNull();
    await act(async () =>
      root.render(inWorkspace(<SettingsSectionView id="plan" />, kind, role)),
    );
    expect(seen.account).toContainEqual(
      expect.objectContaining({ only: ["usage", "billing"] }),
    );
  }
});
