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
import {
  WorkspaceAccessProvider,
  type WorkspaceAccessValue,
} from "../workspace-access";

// The ribbon's areas: name, address and whether it is the current one.
const ribbon = (aside: Element | null | undefined) =>
  Array.from(
    aside?.querySelectorAll<HTMLAnchorElement>("a[data-area]") ?? [],
    (link) => [
      link.textContent,
      link.getAttribute("href"),
      link.getAttribute("aria-current"),
    ],
  );
// The panel: its area, then its pages, each with its address and whether lit.
const panelPages = (aside: Element | null | undefined) => {
  const panel = aside?.querySelector("[data-area-panel]");
  return [
    panel?.getAttribute("aria-label"),
    Array.from(
      panel?.querySelectorAll<HTMLAnchorElement>("a[data-place]") ?? [],
      (link) => [
        link.textContent,
        link.getAttribute("href"),
        link.getAttribute("aria-current"),
      ],
    ),
  ];
};

const ORG_OWNER: WorkspaceAccessValue = {
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
};

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
  // Phones (28 Oct 2026 meeting): the + is in the top bar and asks what to
  // add; the tab bar's middle slot is Ask Dipak.
  const mobileAdd = host.querySelector(
    'header button[aria-label="Add a lead, a call or a task"]',
  );
  expect(mobileAdd?.getAttribute("aria-haspopup")).toBe("dialog");
  const ask = mobileNav?.querySelector('button[aria-label="Ask Dipak"]');
  expect(ask?.textContent?.trim()).toBe("Ask Dipak");
  expect(ask?.getAttribute("aria-haspopup")).toBe("dialog");
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
  // A ribbon of areas and a panel of the current area's pages (owner, dev
  // #8, 26 Oct 2026): New analysis belongs to Work. Team shows only in an
  // organisation. The ribbon marks its area as current, not as the page.
  expect(ribbon(desktopNav)).toEqual([
    ["Home", "/dashboard", null],
    ["Work", "/leads", "true"],
    ["Results", "/reports", null],
  ]);
  expect(panelPages(desktopNav)).toEqual([
    "Work",
    [
      ["Leads", "/leads", null],
      ["Chats", "/chats", null],
      ["Calls", "/analysis/calls", null],
      ["Prospects", "/prospects", null],
    ],
  ]);
  // New analysis is the panel's one button, lit while it is open.
  expect(
    desktopNav?.querySelectorAll('a[aria-label="New analysis"]'),
  ).toHaveLength(1);
  expect(desktopNav?.querySelector('[aria-current="page"]')?.textContent).toBe(
    "New analysis",
  );
  const mobileCalls = Array.from(
    mobileNav?.querySelectorAll<HTMLAnchorElement>(
      'a[data-next-client-link="true"]',
    ) ?? [],
  ).find((link) => link.textContent?.trim() === "Reports");
  // Reports opens on All Calls (Dipak's handoff, 31 Oct 2026).
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

it("makes the sidebar's search a quiet row that opens the command bar", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <AcquisitionShell authenticated active="dashboard">
      <p>Dashboard</p>
    </AcquisitionShell>,
  );
  // One search (owner, dev #8), a quiet row since owner bug #26 (29 Oct
  // 2026): it opens the command bar (Ctrl K), which finds places, leads and
  // calls. The server cannot know the keyboard: it assumes Ctrl, not ⌘.
  expect(host.querySelector('aside form[role="search"]')).toBeNull();
  const pill = host.querySelector(
    'aside button[aria-keyshortcuts^="Control+K"]',
  );
  expect(pill?.textContent).toContain("Search");
  expect(pill?.getAttribute("aria-haspopup")).toBe("dialog");
  expect(pill?.querySelector("kbd")?.textContent).toBe("Ctrl K");
  // The top bar keeps its own for a collapsed sidebar (the styles show one
  // at a time).
  expect(
    host.querySelectorAll('button[aria-keyshortcuts^="Control+K"]'),
  ).toHaveLength(2);
  // Home has one page: the panel lists nothing under its search and New
  // analysis (orchestrator, 26 Oct 2026: "Home" over one row, "Home").
  const aside = host.querySelector('aside[aria-label="Sales Xray navigation"]');
  expect(ribbon(aside)[0]).toEqual(["Home", "/dashboard", "true"]);
  expect(aside?.querySelector("[data-area-panel]")).toBeNull();
  // One toggle at the ribbon's foot hides or shows the panel, with its key.
  const toggle = aside?.querySelector<HTMLButtonElement>(
    'button[aria-controls="sales-xray-sidebar-panel"]',
  );
  expect(toggle?.getAttribute("aria-label")).toBe(
    "Collapse sidebar navigation",
  );
  expect(toggle?.getAttribute("aria-expanded")).toBe("true");
  expect(toggle?.getAttribute("aria-keyshortcuts")).toBe("[");
  expect(toggle?.dataset.railTip).toBe("Hide the panel  [");
  expect(
    aside?.querySelectorAll('button[aria-controls="sales-xray-sidebar-panel"]'),
  ).toHaveLength(1);
});

it("lists Results' pages on Coaching", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <AcquisitionShell authenticated active="coaching">
      <p>Coaching</p>
    </AcquisitionShell>,
  );
  const aside = host.querySelector('aside[aria-label="Sales Xray navigation"]');
  expect(ribbon(aside).map(([label, , current]) => [label, current])).toEqual([
    ["Home", null],
    ["Work", null],
    ["Results", "true"],
  ]);
  expect(panelPages(aside)).toEqual([
    "Results",
    [
      ["Reports", "/reports", null],
      ["Coaching", "/coaching", "page"],
    ],
  ]);
});

// Dipak's handoff (31 Oct 2026): Home, Leads, Ask Dipak, Reports, Growth.
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
        ? ["Home", "Leads", "Ask Dipak", "Reports", "Growth", "Settings"]
        : ["Home", "Leads", "Ask Dipak", "Reports", "Growth"],
    );
    // Prospects and Coaching open from You, not from the tab bar.
    expect(nav.querySelector('a[href="/prospects"]')).toBeNull();
    expect(nav.querySelector('a[href="/coaching"]')).toBeNull();
    // Chats is an icon in the Leads header, not a tab.
    expect(nav.querySelector('a[href="/chats"]')).toBeNull();
    expect(nav.querySelector('a[href="/growth"]')).not.toBeNull();
    // Ask Dipak is the only tab that is a button: it opens his sheet (the
    // dev settings control is the other button, and only with live data).
    expect(
      Array.from(nav.querySelectorAll("button"), (button) =>
        button.textContent?.trim(),
      ),
    ).toEqual(liveData ? ["Ask Dipak", "Settings"] : ["Ask Dipak"]);
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
  ).toEqual(["Home", "Leads", "Ask Dipak", "Reports", "Growth"]);
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
    <WorkspaceAccessProvider value={ORG_OWNER}>
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
  // In an organisation Team joins the ribbon, and Leads has All leads.
  const aside = host.querySelector('aside[aria-label="Sales Xray navigation"]');
  expect(ribbon(aside).map(([label, , current]) => [label, current])).toEqual([
    ["Home", null],
    ["Work", "true"],
    ["Team", null],
    ["Results", null],
  ]);
  expect(
    Array.from(
      aside?.querySelectorAll("[data-area-panel] a[data-sub]") ?? [],
      (link) => [link.textContent, link.getAttribute("href")],
    ),
  ).toEqual([["All leads", "/leads?tab=all&stage=open"]]);
  expect(
    aside?.querySelector('[data-area-panel] [aria-current="page"]')
      ?.textContent,
  ).toBe("Calls");
});

it("lists every hub section under Team, Insights and Plan & billing included", () => {
  const render = (active: "organisation" | "insights") => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <WorkspaceAccessProvider value={ORG_OWNER}>
        <AcquisitionShell authenticated active={active}>
          <p>Organisation</p>
        </AcquisitionShell>
      </WorkspaceAccessProvider>,
    );
    return host.querySelector('aside[aria-label="Sales Xray navigation"]');
  };
  // On a computer the panel is the hub's only section nav (orchestrator,
  // 26 Oct 2026): the hub's own list, in its order.
  const hub = render("organisation");
  expect(panelPages(hub)).toEqual([
    "Team",
    [
      ["Overview", "/organisation", "page"],
      ["Team", "/organisation?tab=team", null],
      ["Analytics", "/organisation?tab=analytics", null],
      ["Insights", "/organisation/insights", null],
      ["Leads setup", "/organisation?tab=leads", null],
      ["Connections", "/organisation?tab=connections", null],
      ["AI on calls", "/organisation?tab=call-ai", null],
      ["Company", "/organisation?tab=company", null],
      ["Plan & billing", "/settings/plan", null],
    ],
  ]);
  expect(
    hub
      ?.querySelector('a[data-place="organisation"]')
      ?.getAttribute("aria-label"),
  ).toBe("Organisation overview");
  // Insights is one of Team's sections now, lit on its page.
  const insights = render("insights");
  expect(ribbon(insights).find(([label]) => label === "Team")?.[2]).toBe(
    "true",
  );
  const [, rows] = panelPages(insights) as [string, string[][]];
  expect(rows.filter((row) => row[2] === "page")).toEqual([
    ["Insights", "/organisation/insights", "page"],
  ]);
});

// Owner bug #26 (29 Oct 2026): the organisation's panel is calm, its pages
// only, the lit one carrying the fill that glides; recent calls stay with
// the areas calls belong to.
it("keeps the Team panel to its pages, without recent calls", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <WorkspaceAccessProvider value={ORG_OWNER}>
      <AcquisitionShell authenticated active="organisation">
        <p>Organisation</p>
      </AcquisitionShell>
    </WorkspaceAccessProvider>,
  );
  const aside = host.querySelector('aside[aria-label="Sales Xray navigation"]');
  expect(panelPages(aside)[0]).toBe("Team");
  expect(aside?.textContent).not.toContain("Recents");
  const rows = aside?.querySelectorAll("[data-area-panel] a[data-place]");
  expect(rows?.length).toBeGreaterThan(1);
  for (const row of rows ?? [])
    expect(row.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
});

it("puts Chats in the Leads header only (Dipak's handoff, 31 Oct 2026)", () => {
  const header = (active: "leads" | "dashboard") => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <AcquisitionShell authenticated active={active}>
        <p>Page</p>
      </AcquisitionShell>,
    );
    return host.querySelector('header a[aria-label="Chats"]');
  };
  expect(header("leads")?.getAttribute("href")).toBe("/chats");
  expect(header("dashboard")).toBeNull();
});
