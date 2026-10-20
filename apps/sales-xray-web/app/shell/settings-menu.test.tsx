import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { SettingsMenu } from "./settings-menu";
import type { Allowance } from "../acquisition-client";
import { guideOffKey } from "../guide-progress";
import { FIRST_CALL_GUIDE } from "../guide-registry";
import { SHEET_PHONE_QUERY } from "../ui/sheet";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "../workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const realMatchMedia = window.matchMedia;

function asPhone(phone: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: query === SHEET_PHONE_QUERY ? phone : false,
      addEventListener() {},
      removeEventListener() {},
    }),
  });
}

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: realMatchMedia,
  });
  vi.unstubAllGlobals();
});

type Props = Partial<Parameters<typeof SettingsMenu>[0]>;

async function open(props: Props = {}, access?: WorkspaceAccessValue) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const menu = (
    <SettingsMenu
      open
      anchorRef={{ current: document.createElement("button") }}
      onClose={() => {}}
      name="Fictional User"
      email="fictional@example.test"
      allowance={null}
      {...props}
    />
  );
  await act(async () =>
    root.render(
      access ? (
        <WorkspaceAccessContext.Provider value={access}>
          {menu}
        </WorkspaceAccessContext.Provider>
      ) : (
        menu
      ),
    ),
  );
  return (
    document.querySelector<HTMLElement>(
      '[role="dialog"][aria-label="Account menu"]',
    ) ?? document.querySelector<HTMLElement>("dialog[open]")!
  );
}

it("opens beside the gear on a computer, inside the window", async () => {
  asPhone(false);
  const anchor = document.createElement("a");
  anchor.getBoundingClientRect = () =>
    ({
      left: 12,
      right: 52,
      top: 700,
      bottom: 740,
      width: 40,
      height: 40,
    }) as DOMRect;
  const menu = await open({ anchorRef: { current: anchor } });
  expect(menu.style.getPropertyValue("--card-left")).toBe("62px");
  expect(Number.parseFloat(menu.style.getPropertyValue("--card-bottom"))).toBe(
    window.innerHeight - 740,
  );
});

it("opens as a sheet on a phone, named Account, which swipes away", async () => {
  asPhone(true);
  const sheet = await open();
  expect(sheet.tagName).toBe("DIALOG");
  const title = document.getElementById(
    sheet.getAttribute("aria-labelledby")!,
  );
  expect(title?.textContent).toBe("Account");
  expect(sheet.textContent).toContain("Fictional User");
  expect(sheet.textContent).toContain("Log out");
});

it.each<[Allowance, string | null]>([
  [
    {
      allowance_seconds: 600000,
      available_seconds: 600000,
      committed_seconds: 0,
    },
    "166 h 40 min left",
  ],
  [
    {
      allowance_seconds: 0,
      available_seconds: 0,
      committed_seconds: 0,
      unlimited: true,
    },
    null,
  ],
])("does not invent a plan for %j", async (allowance, text) => {
  asPhone(false);
  const menu = await open({ allowance });
  const plan = menu.querySelector<HTMLAnchorElement>(
    'a[href="/settings/plan"]',
  )!;
  expect(plan.textContent).toContain("Plan & usage");
  if (text) expect(plan.textContent).toContain(text);
  else expect(plan.textContent).toBe("Plan & usage");
  expect(menu.textContent).not.toMatch(/Unlimited|unavailable|Trial/i);
});

it("lists only what a person needs: Settings, Plan & usage, What's new, Help", async () => {
  asPhone(false);
  const menu = await open({ organisation: true });
  const rows = [...menu.querySelectorAll<HTMLElement>("a, button")].map(
    (row) => row.textContent?.trim(),
  );
  expect(rows).toEqual(
    expect.arrayContaining([
      "Log out",
      "Settings",
      "Plan & usage",
      "What's new",
      "Help & support",
    ]),
  );
  expect(menu.querySelector('a[href="/settings"]')).not.toBeNull();
  expect(menu.querySelector('a[href="/settings/help"]')).not.toBeNull();
  // Owner, 20 Oct: "Taking new leads" lives on the Leads desk, not here;
  // profile, language and billing live in Settings.
  expect(menu.textContent).not.toMatch(
    /Taking new leads|Language|Plans|Profile|billing/,
  );
});

it("switches the first-call guide off and back on from the account menu", async () => {
  asPhone(false);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 503 })),
  );
  localStorage.clear();
  const onClose = vi.fn();
  await open(
    { onClose },
    {
      status: "ready",
      authenticated: true,
      context: { personId: "fictional-a", sessionId: "s", tenantId: "t" },
      retry: () => {},
    },
  );
  const toggle = document.querySelector<HTMLButtonElement>('[role="switch"]')!;
  expect(toggle.textContent).toContain("First call guide");
  expect(toggle.getAttribute("aria-checked")).toBe("true");
  await act(async () => toggle.click());
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  expect(
    localStorage.getItem(guideOffKey("fictional-a", FIRST_CALL_GUIDE)),
  ).toBe("1");
  expect(onClose).not.toHaveBeenCalled();
  await act(async () => toggle.click());
  expect(toggle.getAttribute("aria-checked")).toBe("true");
  expect(
    localStorage.getItem(guideOffKey("fictional-a", FIRST_CALL_GUIDE)),
  ).toBeNull();
  expect(onClose).toHaveBeenCalledTimes(1);
});

it.each(["main", "news"] as const)(
  "shows Draft notes and acknowledges displayed keys from the %s view",
  async (initialView) => {
    asPhone(false);
    let seen = false;
    const fetcher = vi.fn().mockImplementation((path: string) => {
      if (path === "/v1/updates/seen") seen = true;
      return Promise.resolve(
        Response.json(
          path === "/v1/updates"
            ? {
                updates: [
                  {
                    key: "fictional-note",
                    version: 1,
                    release_id: "fictional",
                    date: "2026-10-05",
                    title: "Updates follow your account",
                    items: ["A fictional improvement"],
                    major: false,
                    draft: true,
                    published_at: null,
                    seen,
                  },
                ],
                unseen_count: seen ? 0 : 1,
              }
            : path === "/v1/notifications"
              ? { notifications: [], unread_count: 0 }
              : { unseen_count: 0 },
        ),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    const menu = await open(
      { initialView },
      {
        status: "ready",
        authenticated: true,
        context: {
          personId: `fictional-news-${initialView}`,
          sessionId: "s",
          tenantId: "t",
        },
        retry: () => {},
      },
    );
    const news = [...menu.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("What's new"),
    )!;
    if (initialView === "main") {
      expect(news.textContent).toContain("1 new");
      expect(
        fetcher.mock.calls.some(([path]) => path === "/v1/updates/seen"),
      ).toBe(false);
      await act(async () => news.click());
    }
    expect(menu.textContent).toContain("Draft");
    expect(menu.textContent).toContain("Updates follow your account");
    expect(menu.textContent).toContain("A fictional improvement");
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/updates/seen",
      expect.objectContaining({
        body: JSON.stringify({ keys: ["fictional-note"] }),
      }),
    );
    await act(async () =>
      menu.querySelector<HTMLButtonElement>("button")!.click(),
    );
    expect(menu.textContent).not.toContain("1 new");
  },
);

it("has no guide switch without a signed-in person", async () => {
  asPhone(false);
  await open({ name: null, email: null });
  expect(document.querySelector('[role="switch"]')).toBeNull();
});

it("puts the current workspace first on a phone, others one tap away", async () => {
  asPhone(true);
  const onSelectWorkspace = vi.fn();
  const onClose = vi.fn();
  const sheet = await open({
    onClose,
    workspaces: [
      { tenant_id: "org-one", kind: "organisation", name: "AC", role: "admin" },
      { tenant_id: "personal-one", kind: "personal", name: "Fictional" },
    ],
    currentWorkspaceId: "org-one",
    onSelectWorkspace,
  });
  const group = sheet.querySelector('[aria-label="Workspace"]')!;
  const current = group.querySelector('[aria-current="true"]')!;
  expect(current.textContent).toContain("AC");
  expect(current.textContent).toContain("Organisation · Admin");
  const personal = [...group.querySelectorAll("button")].find((row) =>
    row.textContent?.includes("Personal · Just you"),
  )!;
  expect(personal.querySelector("b")?.textContent).toBe("Personal");
  await act(async () => (current as HTMLButtonElement).click());
  expect(onSelectWorkspace).not.toHaveBeenCalled();
  await act(async () => personal.click());
  expect(onClose).toHaveBeenCalled();
  expect(onSelectWorkspace).toHaveBeenCalledWith("personal-one");
});

it("offers invitations and Create apart, even with one workspace", async () => {
  asPhone(true);
  const onCreateOrganisation = vi.fn();
  const onClose = vi.fn();
  const sheet = await open({
    onClose,
    workspaces: [
      { tenant_id: "personal-one", kind: "personal", name: "Fictional" },
    ],
    currentWorkspaceId: "personal-one",
    onSelectWorkspace: () => {},
    invitesWaiting: 2,
    onCreateOrganisation,
  });
  const group = sheet.querySelector('[aria-label="Workspace"]')!;
  // One workspace is not a choice: no row for it.
  expect(group.textContent).not.toContain("Personal");
  const invitations = group.querySelector<HTMLAnchorElement>(
    'a[href="/organisation/invites"]',
  )!;
  expect(invitations.textContent).toContain("Invitations");
  expect(invitations.textContent).toContain("2");
  const create = [...group.querySelectorAll("button")].find(
    (row) => row.textContent === "Create an organisation",
  )!;
  await act(async () => create.click());
  expect(onClose).toHaveBeenCalled();
  expect(onCreateOrganisation).toHaveBeenCalledTimes(1);
});

it("offers Log out next to who is signed in, without focusing it", async () => {
  asPhone(false);
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(null, { status: 503 }));
  vi.stubGlobal("fetch", fetchMock);
  const menu = await open();
  const logOut = [...menu.querySelectorAll("button")].find(
    (button) => button.textContent === "Log out",
  )!;
  // Owner, 17 Oct: in the first block of the menu, beside the name.
  expect(logOut.parentElement?.textContent).toContain("Fictional User");
  expect(document.activeElement).not.toBe(logOut);
  await act(async () => logOut.click());
  expect(fetchMock).toHaveBeenCalledWith(
    "/v1/auth/logout",
    expect.objectContaining({ method: "POST" }),
  );
  // An unconfirmed sign out leaves the button ready to try again.
  expect(logOut.disabled).toBe(false);
});

it("lists the pages that are not phone tabs, organisation pages only in one", async () => {
  asPhone(true);
  const pages = async (organisation: boolean) => {
    const sheet = await open({ organisation, insights: organisation });
    return [
      ...sheet.querySelectorAll<HTMLAnchorElement>(
        'nav[aria-label="More pages"] a',
      ),
    ].map((link) => link.getAttribute("href"));
  };
  expect(await pages(false)).toEqual(["/prospects", "/coaching"]);
  await act(async () => root.unmount());
  host.remove();
  expect(await pages(true)).toEqual([
    "/prospects",
    "/coaching",
    "/organisation",
    "/organisation/insights",
  ]);
  // The website has no phone calls to offer.
  expect(document.body.textContent).not.toContain("Calls on this phone");
});

it("keeps the phone pages and workspace list off the computer's card", async () => {
  asPhone(false);
  const menu = await open({
    organisation: true,
    workspaces: [
      { tenant_id: "org-one", kind: "organisation", name: "AC" },
      { tenant_id: "personal-one", kind: "personal", name: "Fictional" },
    ],
    currentWorkspaceId: "org-one",
    onSelectWorkspace: () => {},
  });
  expect(menu.querySelector('nav[aria-label="More pages"]')).toBeNull();
  expect(menu.querySelector('[aria-label="Workspace"]')).toBeNull();
});

it("offers Phone setup in the More sheet inside the phone app only", async () => {
  asPhone(true);
  const bridge = window as Window & { SXPhone?: unknown };
  const pages = async () => {
    const sheet = await open({ organisation: false, insights: false });
    return [
      ...sheet.querySelectorAll<HTMLAnchorElement>(
        'nav[aria-label="More pages"] a',
      ),
    ].map((link) => link.getAttribute("href"));
  };
  expect(await pages()).not.toContain("/leads#phone-setup");
  await act(async () => root.unmount());
  host.remove();
  bridge.SXPhone = { postMessage: () => {}, addEventListener: () => {} };
  try {
    expect(await pages()).toContain("/leads#phone-setup");
    expect(document.body.textContent).toContain("Phone setup");
  } finally {
    delete bridge.SXPhone;
  }
});

it("asks the server for nothing while closed, though it stays mounted", async () => {
  asPhone(false);
  const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 503 }));
  vi.stubGlobal("fetch", fetcher);
  await open(
    { open: false },
    {
      status: "ready",
      authenticated: true,
      context: { personId: "fictional-closed", sessionId: "s", tenantId: "t" },
      retry: () => {},
    },
  );
  expect(fetcher).not.toHaveBeenCalled();
});
