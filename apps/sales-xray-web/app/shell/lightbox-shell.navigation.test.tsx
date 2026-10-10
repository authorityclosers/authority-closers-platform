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
  const mobileNewAnalysis = Array.from(
    mobileNav?.querySelectorAll<HTMLAnchorElement>(
      'a[data-next-client-link="true"]',
    ) ?? [],
  ).find((link) => link.textContent?.trim() === "New");
  expect(desktopNewAnalysis?.getAttribute("href")).toBe("/sales-xray?new=1");
  expect(mobileNewAnalysis?.getAttribute("href")).toBe("/sales-xray?new=1");
  expect(mobileNewAnalysis?.getAttribute("aria-label")).toBe("New analysis");
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

  // The phone bar carries no account pill: More in the tab bar opens it.
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
  // The server cannot know the keyboard: it assumes Ctrl, not ⌘.
  expect(form?.querySelector("kbd")?.textContent).toBe("Ctrl K");
});

it("reaches every section from the phone tab bar, plus a dev settings control", () => {
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
        ? ["Dashboard", "Calls", "New", "Prospects", "More", "Settings"]
        : ["Dashboard", "Calls", "New", "Prospects", "More"],
    );
    expect(nav.querySelector('a[href="/prospects"]')?.textContent?.trim()).toBe(
      "Prospects",
    );
    const more = Array.from(nav.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "More",
    );
    expect(more?.getAttribute("aria-haspopup")).toBe("dialog");
    expect(
      nav.querySelector('[aria-current="page"]')?.getAttribute("href"),
    ).toBe("/dashboard");
    expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  }
});

it("keeps More for an unconfirmed session and offers Sign in once signed out", () => {
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
    ).at(-1),
  ).toBe("More");
  expect(
    tabs(
      <AcquisitionShell authenticated={false} active="dashboard">
        <p>Dashboard</p>
      </AcquisitionShell>,
    ).at(-1),
  ).toBe("Sign in");
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
  // Phones: the workspace sits on a small line above the page title (r17).
  const phone = host.querySelector("header span[title] b")?.parentElement;
  expect(phone?.querySelector("small")?.textContent).toBe("Authority Closers");
  expect(phone?.querySelector("b")?.textContent).toBe("Calls");
});
