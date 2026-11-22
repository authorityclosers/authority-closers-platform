// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// sx-redesign (owner, 21 Nov 2026): the Settings hub, board pick C.
const reads = vi.hoisted(() => ({
  setup: vi.fn(),
  team: vi.fn(),
  ai: vi.fn(),
  company: vi.fn(),
  seats: vi.fn(),
  health: vi.fn(),
  notify: vi.fn(),
  theme: { preference: "light", setPreference: vi.fn() },
  signOut: vi.fn(),
  routing: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/settings",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));
vi.mock("../capture-setup/capture-setup-client", () => ({
  readCaptureSetup: reads.setup,
  readCaptureTeam: reads.team,
}));
vi.mock("./ai-apps-client", () => ({ readAiApps: reads.ai }));
vi.mock("../organisation/organisation-api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readOrganisationSettings: reads.company,
  readSeats: reads.seats,
}));
vi.mock("./connected-apps-client", () => ({ readHealth: reads.health }));
vi.mock("../leads/routing-client", () => ({
  readRouting: reads.routing,
  ROUTING_CHANGED: "sx:routing-changed",
}));
vi.mock("./notifications-client", () => ({ readNotify: reads.notify }));
vi.mock("../lightbox/theme-provider", () => ({
  useTheme: () => reads.theme,
}));
vi.mock("../account-navigation", () => ({
  useSalesXraySignOut: () => ({
    signOut: reads.signOut,
    signingOut: false,
    error: "",
  }),
}));
vi.mock("../shell/profile-store", () => ({
  useShellProfile: () => ({
    name: "Priya Fictional",
    email: "priya@example.invalid",
    photo_url: null,
  }),
}));

import { WorkspaceAccessContext } from "../workspace-access";
import {
  SettingsHub,
  groupHref,
  groupLine,
  recordingState,
} from "./settings-hub";
import { SETTINGS_SECTIONS } from "./settings-sections";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
const phone = {
  device: "d1",
  model: "Fictional 9",
  app_version: "1.0.143",
  at: "2026-11-20T10:00:00Z",
  recordings: true,
  background: true,
  uploads: true,
};
const captureSetup = (over: Record<string, unknown> = {}) => ({
  schema: "sales-xray-capture-setup/1",
  workspace: "organisation",
  required: true,
  consent: "on",
  declined_at: null,
  ask_again_at: null,
  phones: [phone],
  ...over,
});
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  reads.setup.mockResolvedValue(captureSetup());
  reads.ai.mockResolvedValue([{ id: "a" }, { id: "b" }]);
  reads.company.mockResolvedValue({ logo_url: "/logo" });
  reads.seats.mockResolvedValue({ activeMembers: 6, pendingInvites: 0 });
  reads.health.mockResolvedValue({
    apps: [{ state: "not_connected", connections: [] }],
  });
  reads.notify.mockResolvedValue({ working_hours: null });
  reads.team.mockResolvedValue({
    people: [
      { name: "Rohan Fictional", state: "phone_pending" },
      { name: "Asha Fictional", state: "set_up" },
    ],
    missingToday: 0,
  });
  reads.signOut.mockReset();
  reads.theme.setPreference.mockReset();
  reads.routing.mockReset();
  reads.routing.mockResolvedValue({
    rules: [
      {
        id: "s",
        name: "Split new leads",
        enabled: true,
        when: [],
        give_to: ["a", "b", "c"],
        shares: [20, 40, 40],
      },
    ],
    people: [
      { person_id: "a", name: "Farah Fictional" },
      { person_id: "b", name: "Priya Fictional" },
      { person_id: "c", name: "Rohan Fictional" },
    ],
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
    <SettingsHub />
  </WorkspaceAccessContext.Provider>
);

const settle = () =>
  act(async () => {
    for (let n = 0; n < 6; n++) await Promise.resolve();
  });

it("gives an owner the setup hero, one green button and a card for each group", async () => {
  await act(async () => root.render(inOrg("owner")));
  await settle();
  expect(host.querySelector("[data-hub]")?.getAttribute("data-hub")).toBe(
    "owner",
  );
  expect(host.textContent).toContain("Your company is 2 of 5 set up");
  // Exactly one solid button: the next step's.
  const buttons = host.querySelectorAll('a[data-sx-feature^="setup_"]');
  expect([...buttons].map((link) => link.textContent)).toEqual(["Connect"]);
  expect(buttons[0]?.getAttribute("href")).toBe("/settings/apps");
  // Short lines from the same reads.
  const line = (slug: string) =>
    host.querySelector(`a[data-group="${slug}"] [class*="line"]`)?.textContent;
  expect(line("team")).toBe("6 people");
  expect(line("calls-phones")).toBe("Sellers' phones 1 of 2 ready");
  expect(line("connections")).toBe("Nothing connected yet");
  expect(line("company")).toBe("Logo and details added");
  expect(line("leads")).toBe("Lead split, rules, stages and sources");
  // No Sign out or theme on the owner's hub (they live in Just me).
  expect(host.textContent).not.toContain("Sign out");
});

it("gives a seller recording on, who they are, short rows, Look and Sign out", async () => {
  await act(async () => root.render(inOrg("member")));
  await settle();
  expect(host.querySelector("[data-hub]")?.getAttribute("data-hub")).toBe(
    "personal",
  );
  const hero = host.querySelector('section[aria-label="Call recording"]');
  expect(hero?.querySelector("h2")?.textContent).toBe("Call recording is on");
  expect(hero?.textContent).toContain("Phone setup done");
  expect(hero?.textContent).toContain("App 1.0.143");
  // All is fine: no button at all.
  expect(hero?.querySelector("a, button")).toBeNull();
  expect(host.textContent).toContain("Priya Fictional");
  expect(host.textContent).toContain("Seller · Fictional Homes");
  expect(host.querySelector('a[href="/settings/profile"]')?.textContent).toBe(
    "Edit profile",
  );
  const rows = (label: string) =>
    [...host.querySelectorAll(`section[aria-label="${label}"] a`)].map((link) =>
      link.getAttribute("href"),
    );
  expect(rows("Just me")).toEqual([
    "/settings/selling",
    "/settings/sounds",
    "/settings/security",
    "/settings/ai-apps",
    "/settings/privacy",
    "/settings/help",
  ]);
  expect(rows("This phone")).toEqual([
    "/settings/notifications",
    "/settings/devices",
  ]);
  // A seller still reaches the team, the company and analysis time; no billing.
  expect(rows("For everyone")).toEqual([
    "/settings/team",
    "/settings/organisation",
    "/settings/analysis-time",
  ]);
  expect(
    host.querySelector('a[data-section="ai-apps"] [class*="value"]')
      ?.textContent,
  ).toBe("2 on");
  // Look: Light | Dark pills.
  const dark = [...host.querySelectorAll('[role="radio"]')].find(
    (pill) => pill.textContent === "Dark",
  ) as HTMLButtonElement;
  expect(dark.getAttribute("aria-checked")).toBe("false");
  await act(async () => dark.click());
  expect(reads.theme.setPreference).toHaveBeenCalledWith("dark");
  // Sign out: the last row, red words, signs out.
  const out = [...host.querySelectorAll("button")].at(-1) as HTMLButtonElement;
  expect(out.textContent).toBe("Sign out");
  await act(async () => out.click());
  expect(reads.signOut).toHaveBeenCalled();
});

it("shows one button only when recording needs something", async () => {
  reads.setup.mockResolvedValue(captureSetup({ consent: "off" }));
  await act(async () => root.render(inOrg("member")));
  await settle();
  const hero = host.querySelector('section[aria-label="Call recording"]');
  expect(hero?.querySelector("h2")?.textContent).toBe("Call recording is off");
  const go = hero?.querySelector("a");
  expect(go?.textContent).toBe("Turn on call recording");
  expect(go?.getAttribute("href")).toBe("/settings/privacy");
});

it("works out recording, card lines and where a card goes", () => {
  expect(recordingState(captureSetup() as never)).toEqual({
    kind: "on",
    app: "1.0.143",
  });
  expect(recordingState(captureSetup({ phones: [] }) as never)).toEqual({
    kind: "no-phone",
  });
  expect(
    recordingState(
      captureSetup({ phones: [{ ...phone, recordings: false }] }) as never,
    ),
  ).toEqual({ kind: "fix" });
  // A personal workspace that never needed it: no hero.
  expect(
    recordingState(captureSetup({ required: false, consent: "ask" }) as never),
  ).toBeNull();
  const only = SETTINGS_SECTIONS.filter((item) => item.group === "Company");
  expect(groupHref("Company", only)).toBe("/settings/organisation");
  expect(groupHref("Leads", [])).toBe("/settings/group/leads");
  expect(groupLine("Team", { people: 1, invited: 2 })).toBe(
    "1 person · 2 invited",
  );
  expect(groupLine("Connections", { appsConnected: 3 })).toBe(
    "3 apps connected",
  );
  expect(groupLine("Plan & billing", null)).toBe("Plan and analysis time");
});

it("puts who gets new leads first on an owner's hub, opening the split (v1.94)", async () => {
  await act(async () => root.render(inOrg("owner")));
  await settle();
  const card = host.querySelector<HTMLAnchorElement>("a[data-split]");
  expect(card?.getAttribute("href")).toBe("/settings/lead-rules");
  expect(card?.textContent).toContain("Who gets new leads");
  expect(card?.textContent).toContain(
    "Split by percent: Farah 20 %, Priya 40 % …",
  );
  // Right after the setup hero, before the company's cards.
  const blocks = [...host.querySelectorAll("section[aria-label]")].map(
    (section) => section.getAttribute("aria-label"),
  );
  expect(blocks.indexOf("Who gets new leads")).toBeLessThan(
    blocks.indexOf("For everyone"),
  );
});

it("says the split is off in plain words", async () => {
  reads.routing.mockResolvedValue({ rules: [], people: [] });
  await act(async () => root.render(inOrg("owner")));
  await settle();
  expect(host.querySelector("a[data-split]")?.textContent).toContain(
    "Off: whoever is free gets the next lead",
  );
});

it("never shows a seller the split card, nor reads the rules", async () => {
  await act(async () => root.render(inOrg("member")));
  await settle();
  expect(host.querySelector("a[data-split]")).toBeNull();
  expect(host.textContent).not.toContain("Who gets new leads");
  expect(reads.routing).not.toHaveBeenCalled();
});
