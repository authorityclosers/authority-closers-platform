// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

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
vi.mock("./connected-apps", () => ({
  ConnectedApps: () => <p data-testid="connected-apps">apps grid</p>,
}));

import { SettingsSectionView } from "./sections";
import { SettingsSkeleton } from "./settings-skeleton";
import { AccountRedirect } from "./account-redirect";
import SettingsPage from "./page";
import { SettingsShell, currentSection } from "./settings-shell";
import {
  SETTINGS_SECTIONS,
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
    "security",
    "plan",
    "organisation",
    "team",
    "apps",
    "ai-replies",
    "developers",
    "notifications",
    "devices",
    "help",
  ]);
  expect(settingsPath("team")).toBe("/settings/team");
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
  // Once in the side list (computers), once as cards (the page itself).
  expect(new Set(links.map((link) => link.getAttribute("href")))).toEqual(
    new Set(SETTINGS_SECTIONS.map((item) => `/settings/${item.id}`)),
  );
  expect(
    host.querySelector('nav[aria-label="Settings sections"]'),
  ).not.toBeNull();
  expect(host.textContent).toContain("Connections");
  expect(host.textContent).toContain("Google, Facebook and Apple sign-in");
  expect(host.querySelector("a[aria-current='page']")).toBeNull();
});

it("shows one section with its title, the way back, and the side list lit", async () => {
  nav.pathname = "/settings/team";
  await act(async () =>
    root.render(
      <SettingsShell>
        <p>team section</p>
      </SettingsShell>,
    ),
  );
  expect(host.querySelector("h1")?.textContent).toBe("Team & roles");
  expect(host.querySelector('a[href="/settings"]')?.textContent).toContain(
    "Settings",
  );
  expect(
    host.querySelector("a[aria-current='page']")?.getAttribute("href"),
  ).toBe("/settings/team");
  expect(host.textContent).toContain("team section");
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
  await render("developers");
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
    [["integrations"], ["keys", "webhook", "handover", "apps"]],
    [["integrations"], ["ai"]],
  ]);
  // Connected apps is one grid of app cards of its own.
  await render("apps");
  expect(host.querySelector('[data-testid="connected-apps"]')).not.toBeNull();
  await render("devices");
  expect(host.querySelector('a[href="/apps"]')).not.toBeNull();
  expect(host.querySelector('a[href="/leads#phone-setup"]')).not.toBeNull();
  await render("notifications");
  expect(host.textContent).toContain("Lead alerts on your phone");
});

it("sends an old /account address to its section", async () => {
  window.history.replaceState(null, "", "/account#billing");
  await act(async () => root.render(<AccountRedirect />));
  expect(nav.replace).toHaveBeenCalledWith("/settings/plan");
  expect(host.querySelector('[role="status"]')).not.toBeNull();
  window.history.replaceState(null, "", "/");
});

it("keeps the Settings frame while the session is checked", async () => {
  nav.pathname = "/settings/apps";
  await act(async () => root.render(<SettingsSkeleton />));
  const status = host.querySelector(
    '[role="status"][aria-label="Loading settings"]',
  );
  expect(status?.getAttribute("aria-busy")).toBe("true");
  expect(host.querySelector("h1")?.textContent).toBe("Connected apps");
  expect(
    host.querySelector("a[aria-current='page']")?.getAttribute("href"),
  ).toBe("/settings/apps");
  // The overview needs no data, so it is the page itself.
  nav.pathname = "/settings";
  await act(async () => root.render(<SettingsSkeleton />));
  expect(host.querySelector("h1")?.textContent).toBe("Settings");
  expect(host.querySelectorAll("a[data-variant='list']")).toHaveLength(
    SETTINGS_SECTIONS.length,
  );
});
