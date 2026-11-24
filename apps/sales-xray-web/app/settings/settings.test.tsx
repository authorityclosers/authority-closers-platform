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
// The hub's own reads answer nothing here (settings-hub.test.tsx has them).
vi.mock("../capture-setup/capture-setup-client", () => ({
  readCaptureSetup: () => Promise.reject(new Error("offline")),
  readCaptureTeam: () => Promise.reject(new Error("offline")),
}));
vi.mock("./ai-apps-client", () => ({
  readAiApps: () => Promise.reject(new Error("offline")),
}));
vi.mock("./ai-apps", () => ({
  AiAppsSection: () => <p data-testid="ai-apps">ai apps</p>,
}));

import { WorkspaceAccessContext } from "../workspace-access";
import { SettingsSectionView } from "./sections";
import { SettingsSkeleton } from "./settings-skeleton";
import { AccountRedirect } from "./account-redirect";
import SettingsPage from "./page";
import {
  OWN_TITLE_ATTRIBUTE,
  SettingsShell,
  currentGroup,
  currentSection,
} from "./settings-shell";
import {
  SETTINGS_SECTIONS,
  accountRedirect,
  hubTabSetting,
  isSettingsSection,
  sectionById,
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
  // Round-2 board 7 (20 Nov 2026): grouped the way an owner thinks.
  expect(SETTINGS_SECTIONS.map((item) => [item.group, item.id])).toEqual([
    ["Team", "team"],
    ["Leads", "lead-rules"],
    ["Leads", "stages"],
    ["Leads", "sources"],
    ["Calls & phones", "phones"],
    ["Calls & phones", "call-ai"],
    ["Calls & phones", "team-sounds"],
    ["Connections", "apps"],
    ["Connections", "ai-replies"],
    ["Connections", "developers"],
    ["Connections", "pulse"],
    ["Company", "organisation"],
    ["Plan & billing", "plan"],
    ["Plan & billing", "analysis-time"],
    ["Just me", "profile"],
    ["Just me", "selling"],
    ["Just me", "sounds"],
    ["Just me", "security"],
    ["Just me", "ai-apps"],
    ["Just me", "privacy"],
    ["Just me", "help"],
    ["This phone", "notifications"],
    ["This phone", "devices"],
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
  // The subtitle names no way in the page may not list (Apple: judge, 21 Nov 2026).
  expect(sectionById("security").hint).toBe("How you sign in, and signing out");
  expect(currentSection("/settings")).toBeNull();
});

it("shows the hub: a card for each group, every section still in the side list", async () => {
  nav.pathname = "/settings";
  await act(async () =>
    root.render(<SettingsShell>{<SettingsPage />}</SettingsShell>),
  );
  // The side list (computers) keeps every section one click away.
  const listed = [
    ...host.querySelectorAll<HTMLAnchorElement>(
      'nav[aria-label="Settings sections"] a[href^="/settings/"]',
    ),
  ];
  expect(new Set(listed.map((link) => link.getAttribute("href")))).toEqual(
    new Set(
      // Privacy and Apps & devices open inside Phone & alerts (owner, 24 Oct 2026).
      SETTINGS_SECTIONS.filter((item) => !item.within).map(
        (item) => `/settings/${item.id}`,
      ),
    ),
  );
  // sx-redesign pick C (owner, 21 Nov 2026): one card a group, under two
  // labels instead of a scope chip on each; a group with one section opens it.
  const cards = (label: string) =>
    [
      ...host.querySelectorAll<HTMLAnchorElement>(
        `[data-hub] section[aria-label="${label}"] a`,
      ),
    ].map((link) => [
      link.querySelector('[class*="name"]')?.textContent,
      link.getAttribute("href"),
    ]);
  expect(cards("For everyone")).toEqual([
    ["Team", "/settings/team"],
    ["Leads", "/settings/group/leads"],
    ["Calls & phones", "/settings/group/calls-phones"],
    ["Connections", "/settings/group/connections"],
    ["Company", "/settings/organisation"],
    ["Plan & billing", "/settings/group/plan-billing"],
  ]);
  expect(cards("Just me")).toEqual([
    ["Just me", "/settings/group/just-me"],
    ["This phone", "/settings/group/this-phone"],
  ]);
  expect(host.querySelector("[data-hub] [data-scope]")).toBeNull();
  expect(host.querySelector("h1")?.textContent).toBe("Settings");
  expect(
    host.querySelector("nav a[aria-current='page']")?.getAttribute("href"),
  ).toBe("/settings");
});

it("opens a group's page with its sections, the way back and who it affects", async () => {
  nav.pathname = "/settings/group/leads";
  const { SettingsGroupView } = await import("./settings-hub");
  await act(async () =>
    root.render(
      <SettingsShell>
        <SettingsGroupView group="Leads" />
      </SettingsShell>,
    ),
  );
  expect(currentGroup("/settings/group/leads")).toBe("Leads");
  expect(currentGroup("/settings/group/nonsense")).toBeNull();
  expect(host.querySelector("h1")?.textContent).toBe("Leads");
  expect(
    host.querySelector("header [data-scope]")?.getAttribute("data-scope"),
  ).toBe("everyone");
  expect(
    host
      .querySelector('header a[title="Back to Settings"]')
      ?.getAttribute("href"),
  ).toBe("/settings");
  expect(
    [...host.querySelectorAll("[data-hub] a")].map((link) =>
      link.getAttribute("href"),
    ),
  ).toEqual(["/settings/lead-rules", "/settings/stages", "/settings/sources"]);
  // Just me lists This phone too, with Privacy and Apps & devices.
  nav.pathname = "/settings/group/just-me";
  await act(async () =>
    root.render(
      <SettingsShell>
        <SettingsGroupView group="Just me" />
      </SettingsShell>,
    ),
  );
  const hrefs = [...host.querySelectorAll("[data-hub] a")].map((link) =>
    link.getAttribute("href"),
  );
  expect(hrefs).toContain("/settings/privacy");
  expect(hrefs).toContain("/settings/notifications");
  expect(hrefs).toContain("/settings/devices");
  expect(host.textContent).toContain("Sign out");
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
  // The way back is a chevron beside the name, named for readers; on the
  // owner's hub it goes one step up, to the group's page (sx-redesign).
  const back = host.querySelector("header a[title]");
  expect(back?.getAttribute("href")).toBe("/settings/group/just-me");
  expect(back?.getAttribute("aria-label")).toBe("Back to Just me");
  expect(back?.textContent).toBe("");
  // The chip beside the title is the short one, the full words its title.
  expect(host.querySelector("header [data-scope]")?.textContent).toBe(
    "Just me",
  );
  // No "Settings" page row over the section's name on a phone.
  expect(document.documentElement.hasAttribute(OWN_TITLE_ATTRIBUTE)).toBe(true);
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
  ).toEqual([["general"], ["billing"], ["security"]]);
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
  // Apps & devices and Phone & alerts each have their own page (v1.96).
  await render("devices");
  // Google Play first; the app file stays under it (24 Oct 2026).
  expect(host.querySelector(`a[href="${PLAY_OPT_IN_URL}"]`)).not.toBeNull();
  expect(host.querySelector(`a[href="${ANDROID_APK_URL}"]`)).not.toBeNull();
  expect(host.textContent).toContain("Look on this device");
  expect(host.textContent).not.toContain("Usage analytics");
  await render("notifications");
  expect(host.textContent).toContain("Usage analytics");
  expect(host.textContent).not.toContain("Sales X-Ray on your phone");
  expect(host.textContent).not.toContain("Appearance");
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
  expect(
    host.querySelectorAll("[data-hub] section[aria-label] a[data-group]"),
  ).toHaveLength(8);
});

// Round-2 board 7 (20 Nov 2026): the organisation's settings live in Settings
// again, each section saying who it affects; the hub's old addresses come here.
it("keeps the organisation's settings here, and its sections say who they affect", async () => {
  nav.pathname = "/settings/stages";
  await act(async () =>
    root.render(
      <SettingsShell>
        <p>stages</p>
      </SettingsShell>,
    ),
  );
  expect(host.querySelector("h1")?.textContent).toBe("Lead stages");
  expect(
    host.querySelector("header [data-scope]")?.getAttribute("data-scope"),
  ).toBe("everyone");
  expect(host.querySelector('a[href="/organisation"]')).toBeNull();
  nav.pathname = "/settings/privacy";
  await act(async () =>
    root.render(
      <SettingsShell>
        <p>privacy</p>
      </SettingsShell>,
    ),
  );
  // Privacy opens inside Phone & alerts: this phone's.
  expect(
    host.querySelector("header [data-scope]")?.getAttribute("data-scope"),
  ).toBe("phone");
  expect(hubTabSetting("leads", "stages")).toBe("/settings/stages");
  expect(hubTabSetting("connections", null)).toBe("/settings/apps");
  expect(hubTabSetting("analytics", null)).toBeNull();
  expect(hubTabSetting(null, null)).toBe("/settings");
});

it("lists only your own settings in a personal workspace", async () => {
  nav.pathname = "/settings";
  await act(async () =>
    root.render(
      inWorkspace(
        <SettingsShell>{<SettingsPage />}</SettingsShell>,
        "personal",
        null,
      ),
    ),
  );
  expect(host.querySelector('a[href="/settings/team"]')).toBeNull();
  expect(host.querySelector('a[href="/settings/apps"]')).toBeNull();
  expect(host.querySelector('a[href="/settings/plan"]')).not.toBeNull();
  expect(host.querySelector('a[href="/settings/sounds"]')).not.toBeNull();
  // Plan & billing is yours there: the seller's hub, under "Plan".
  expect(host.querySelector("[data-hub]")?.getAttribute("data-hub")).toBe(
    "personal",
  );
  expect(
    host.querySelector('section[aria-label="Plan"] a[href="/settings/plan"]'),
  ).not.toBeNull();
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

it("leaves Plan & billing out for a Seller, and says who sees billing at its address", async () => {
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
  expect(host.querySelector("h1")?.textContent).toBe("Plan & billing");
  expect(host.textContent).not.toContain("Your plan and invoices");
  expect(host.textContent).toContain(
    "Only your organisation's owner can see billing.",
  );
});

it("keeps Plan & billing for an organisation's owner and in a personal workspace", async () => {
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
    // Plan & billing alone: no second analysis time or top-up (production 124).
    expect(seen.account).toContainEqual(
      expect.objectContaining({ only: ["billing"] }),
    );
  }
});

it("says Settings once on a phone and lets a row's line wrap", async () => {
  // Redmi QA on production (10 Nov 2026, 363 px at 130% text): "Settings" in
  // the top bar and again as the heading; row lines cut to "phone a...".
  const read = async (name: string) =>
    (await import("node:fs")).readFileSync(
      (await import("node:path")).join(process.cwd(), "app/settings", name),
      "utf8",
    );
  const hub = await read("settings-hub.module.css");
  expect(hub).toMatch(/\.readerOnly \{[^}]*clip-path: inset\(50%\);/);
  const line = /\n\.line \{([^}]*)\}/.exec(hub)?.[1] ?? "";
  expect(line).not.toContain("ellipsis");
  expect(line).not.toContain("nowrap");
  const css = await read("settings-shell.module.css");
  const hint = /\n\.hint \{([^}]*)\}/.exec(css)?.[1] ?? "";
  expect(hint).not.toContain("ellipsis");
  expect(hint).not.toContain("nowrap");
  // The frame's "Settings" row steps aside while a section shows its name.
  expect(css).toContain("html[data-sx-settings-own-title]");
});
