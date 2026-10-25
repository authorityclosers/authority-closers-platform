import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href} data-next-client-link="true">
      {children}
    </a>
  ),
}));

import { AcquisitionShell } from "../acquisition-shell";
import { LiveDataBanner } from "../live-data-banner";
import { recentCallsForContext } from "./shell-store";
import { WorkspaceAccessProvider } from "../workspace-access";

it("only exposes cached recents for the matching account and workspace", () => {
  const cached = {
    recentCalls: [
      { id: "call-1", name: "Fictional call", date: "Sep 29, 2026" },
    ],
    recentCallsContextKey: '["person-1","session-1","tenant-1"]',
  };

  expect(
    recentCallsForContext(cached, '["person-1","session-1","tenant-1"]'),
  ).toEqual(cached.recentCalls);
  expect(
    recentCallsForContext(cached, '["person-2","session-2","tenant-2"]'),
  ).toEqual([]);
  expect(recentCallsForContext(cached, null)).toEqual([]);
});

it("keeps same-shell navigation on the App Router client-link path", () => {
  const html = renderToStaticMarkup(
    <AcquisitionShell authenticated homeHref="/sales-xray">
      <p>Workspace</p>
    </AcquisitionShell>,
  );
  const host = document.createElement("div");
  host.innerHTML = html;

  const desktopNav = host.querySelector(
    'aside[aria-label="Sales Xray navigation"]',
  );
  const mobileNav = host.querySelector(
    'nav[aria-label="Mobile Sales Xray navigation"]',
  );
  const desktopNewAnalysis = desktopNav?.querySelector(
    'a[aria-label="New analysis"][data-next-client-link="true"]',
  );
  expect(desktopNewAnalysis?.getAttribute("href")).toBe("/sales-xray?new=1");
  // Phones: the + asks what to add, a lead or a call (owner, 22 Oct).
  const mobileAdd = mobileNav?.querySelector(
    'button[aria-label="Add a lead or a call"]',
  );
  expect(mobileAdd?.textContent?.trim()).toBe("Add");
  expect(mobileAdd?.getAttribute("aria-haspopup")).toBe("dialog");
  expect(
    desktopNav?.querySelector(
      'a[aria-label="Calls"][href="/analysis/calls"][data-next-client-link="true"]',
    ),
  ).not.toBeNull();
  expect(
    desktopNav?.querySelector(
      'a[aria-label="Prospects"][href="/prospects"][data-next-client-link="true"]',
    ),
  ).not.toBeNull();
  expect(
    desktopNav?.querySelector(
      'a[aria-label="Reports"][href="/reports"][data-next-client-link="true"]',
    ),
  ).not.toBeNull();
  // The places in groups (owner, 25 Oct 2026): the day's work, then how it
  // is going (Reports, then Coaching); the organisation's group shows only
  // inside an organisation.
  const groups = Array.from(
    desktopNav?.querySelectorAll<HTMLElement>('[role="group"]') ?? [],
    (group) => [
      group.getAttribute("aria-label"),
      Array.from(
        group.querySelectorAll<HTMLAnchorElement>("a[data-rail-tip]"),
        (link) => link.dataset.railTip,
      ),
    ],
  );
  expect(groups).toEqual([
    ["Work", ["Home", "Leads", "Chats", "New analysis", "Calls", "Prospects"]],
    ["Performance", ["Reports", "Coaching"]],
  ]);
  expect(
    desktopNav?.querySelector('a[aria-label="Coaching"][href="/coaching"]'),
  ).not.toBeNull();
  const mobileCalls = Array.from(
    mobileNav?.querySelectorAll<HTMLAnchorElement>(
      'a[data-next-client-link="true"]',
    ) ?? [],
  ).find((link) => link.textContent?.trim() === "Calls");
  expect(mobileCalls?.getAttribute("href")).toBe("/analysis/calls");
  expect(
    desktopNav?.querySelector(
      'a[aria-label="Account"][href="/account"][data-next-client-link="true"]',
    ),
  ).not.toBeNull();

  // The phone bar carries no account pill: the avatar in the top bar opens
  // You (the new map, 22 Oct: no More tab).
  expect(
    host.querySelectorAll(
      'button[aria-label="Open AC account menu"][aria-expanded="false"]',
    ),
  ).toHaveLength(1);
  expect(host.querySelector('[aria-label="Profile actions"]')).toBeNull();
});

it("makes the sidebar search open Calls with the typed text", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <AcquisitionShell authenticated active="dashboard">
      <p>Dashboard</p>
    </AcquisitionShell>,
  );
  const form = host.querySelector<HTMLFormElement>('aside form[role="search"]');
  expect(form?.getAttribute("action")).toBe("/analysis/calls");
  expect(
    form
      ?.querySelector('input[type="search"][name="q"]')
      ?.getAttribute("aria-label"),
  ).toBe("Search calls");
  // Ctrl K opens the command bar (slice 9 of the new map): its Search button
  // in the top bar carries the shortcut, not this box. The server cannot know
  // the keyboard: it assumes Ctrl, not ⌘.
  expect(form?.querySelector("kbd")).toBeNull();
  const search = host.querySelector("button[aria-keyshortcuts]");
  expect(search?.textContent).toContain("Search");
  expect(search?.querySelector("kbd")?.textContent).toBe("Ctrl K");
});

// The new map (owner, 22 Oct 2026): Home, Leads, + (Add), Chats, Calls.
it("keeps the phone tab bar to its five tabs, plus a dev settings control", () => {
  for (const liveData of [false, true]) {
    const shell = (
      <AcquisitionShell authenticated active="dashboard">
        <p>Dashboard</p>
      </AcquisitionShell>
    );
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      liveData ? <LiveDataBanner>{shell}</LiveDataBanner> : shell,
    );
    const nav = host.querySelector(
      'nav[aria-label="Mobile Sales Xray navigation"]',
    )!;
    expect(
      Array.from(nav.children, (item) => item.textContent?.trim()),
    ).toEqual(
      liveData
        ? ["Home", "Leads", "Add", "Chats", "Calls", "Settings"]
        : ["Home", "Leads", "Add", "Chats", "Calls"],
    );
    // Prospects and Coaching open from You, not from the tab bar.
    expect(nav.querySelector('a[href="/prospects"]')).toBeNull();
    expect(nav.querySelector('a[href="/coaching"]')).toBeNull();
    // Chats is its own tab now.
    expect(nav.querySelector('a[href="/chats"]')).not.toBeNull();
    // Add is the only tab that is a button: it asks what to add (the dev
    // settings control is the other button, and only with live data).
    expect(
      Array.from(nav.querySelectorAll("button"), (button) =>
        button.textContent?.trim(),
      ),
    ).toEqual(liveData ? ["Add", "Settings"] : ["Add"]);
    expect(
      nav.querySelector('[aria-current="page"]')?.getAttribute("href"),
    ).toBe("/dashboard");
    expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  }
});

it("keeps the five tabs for an unconfirmed session; signed out offers Home, New and Sign in", () => {
  const tabs = (shell: React.ReactElement) => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(shell);
    return Array.from(
      host.querySelector('nav[aria-label="Mobile Sales Xray navigation"]')!
        .children,
      (item) => item.textContent?.trim(),
    );
  };
  expect(
    tabs(
      <AcquisitionShell authenticated={false} loading active="dashboard">
        <p>Dashboard</p>
      </AcquisitionShell>,
    ),
  ).toEqual(["Home", "Leads", "Add", "Chats", "Calls"]);
  // B22: Leads and Calls only lead to a sign-in prompt for a visitor.
  expect(
    tabs(
      <AcquisitionShell authenticated={false} active="dashboard">
        <p>Dashboard</p>
      </AcquisitionShell>,
    ),
  ).toEqual(["Home", "New", "Sign in"]);
});

it("names the current workspace in the phone header and the desktop top bar", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <WorkspaceAccessProvider
      value={{
        status: "ready",
        authenticated: true,
        context: { personId: "p", sessionId: "s", tenantId: "org-one" },
        workspaces: [
          {
            tenant_id: "org-one",
            kind: "organisation",
            name: "Authority Closers",
            role: "owner",
            sales_xray_enabled: true,
          },
          {
            tenant_id: "personal-one",
            kind: "personal",
            name: "Fictional Owner",
            role: null,
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <AcquisitionShell authenticated active="calls">
        <p>Calls</p>
      </AcquisitionShell>
    </WorkspaceAccessProvider>,
  );
  expect(
    host.querySelector('[title="Workspace: Authority Closers"]'),
  ).not.toBeNull();
  expect(
    host.querySelectorAll('[title="Workspace: Authority Closers"]'),
  ).toHaveLength(2);
  // Phones: the workspace sits on a small line above the page title (r17),
  // and with another workspace to go to, a tap there switches (design
  // system v2, owner 20 Oct).
  const phone = host.querySelector("header [title] b")?.parentElement;
  expect(phone?.tagName).toBe("BUTTON");
  expect(phone?.getAttribute("aria-haspopup")).toBe("dialog");
  expect(phone?.querySelector("small")?.textContent).toBe("Authority Closers");
  expect(phone?.querySelector("b")?.textContent).toBe("Calls");
});
