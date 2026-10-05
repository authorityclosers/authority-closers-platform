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

  expect(
    host.querySelectorAll(
      'button[aria-label="Open AC account menu"][aria-expanded="false"]',
    ),
  ).toHaveLength(2);
  expect(host.querySelector('[aria-label="Profile actions"]')).toBeNull();
});

it("offers four phone destinations and a fifth dev settings control", () => {
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
        ? ["Dashboard", "New", "Calls", "Account", "Settings"]
        : ["Dashboard", "New", "Calls", "Account"],
    );
    expect(
      nav.querySelector('[aria-current="page"]')?.getAttribute("href"),
    ).toBe("/dashboard");
    expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  }
});
