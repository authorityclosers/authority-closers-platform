import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AcquisitionShell } from "./acquisition-shell";
import { ThemeProvider } from "./lightbox/theme-provider";
import { updateShellState } from "./shell/shell-store";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const allowance = {
  allowance_seconds: 3600,
  committed_seconds: 1080,
  available_seconds: 2520,
};

function render(markup: string) {
  const host = document.createElement("div");
  host.innerHTML = markup;
  return host;
}

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  updateShellState({ collapsed: false });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
  updateShellState({ collapsed: false });
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-theme-preference");
  document.documentElement.style.colorScheme = "";
  vi.unstubAllGlobals();
});

it("keeps navigation, one main landmark and help, without placeholder chrome", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("offline profile")),
  );
  await act(async () =>
    root.render(
      <AcquisitionShell authenticated heroStage="welcome">
        <p>Workspace content</p>
      </AcquisitionShell>,
    ),
  );
  const shell = host;
  const navigation = shell.querySelector(
    'aside[aria-label="Sales Xray navigation"]',
  )!;
  expect(navigation).not.toBeNull();
  expect(
    navigation
      .querySelector('a[aria-label="New analysis"]')
      ?.getAttribute("href"),
  ).toBe("/analysis/new");
  expect(
    shell
      .querySelector(
        'nav[aria-label="Mobile Sales Xray navigation"] a[aria-current="page"]',
      )
      ?.getAttribute("href"),
  ).toBe("/analysis/new");
  expect(shell.querySelector('a[href="/analysis/calls"]')).not.toBeNull();
  // Account is its own destination, not a second link to Calls.
  const account = navigation.querySelector<HTMLAnchorElement>(
    'a[aria-label="Account"][href="/account"]',
  );
  expect(account?.textContent).toBe("Account");
  expect(shell.textContent).not.toContain("Account & saved calls");
  expect(
    navigation.querySelectorAll(
      'a[aria-label="Calls"][href="/analysis/calls"]',
    ),
  ).toHaveLength(1);
  expect(shell.querySelectorAll("main")).toHaveLength(1);
  expect(shell.querySelector("main")?.id).toBe("main-content");
  expect(shell.querySelector('a[href="#main-content"]')?.textContent).toBe(
    "Skip to workspace",
  );
  expect(shell.querySelector('a[aria-label="Sales Xray home"]')).not.toBeNull();

  // Studio request 2 moves legal/support actions into the header profile menu.
  const trigger = shell.querySelector<HTMLButtonElement>(
    'header button[aria-label="Open AC account menu"]',
  )!;
  trigger.focus();
  await act(async () => trigger.click());
  const legal = shell.querySelector(
    '[role="region"][aria-label="Profile actions"]',
  )!;
  expect(legal).not.toBeNull();
  expect(
    [...legal.querySelectorAll('a[href^="https://"], a[href^="mailto:"]')].map(
      (link) => link.getAttribute("href"),
    ),
  ).toEqual([
    "https://app.authorityclosers.com/privacy",
    "https://app.authorityclosers.com/terms",
    "mailto:admin@authorityclosers.com?subject=Sales%20Xray%20help",
  ]);
  await act(async () =>
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    ),
  );
  expect(shell.querySelector('[aria-label="Profile actions"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);

  for (const removed of [
    "Need help?",
    "Welcome back",
    "Welcome to Sales Xray",
    "TURN CALLS INTO CLARITY",
    "Better",
    "Win more deals",
    "Turn conversations into closers",
  ])
    expect(shell.textContent).not.toContain(removed);
});

it("uses compact, truthful page headings with no greeting or estimated duration", () => {
  const heading = (
    props: Partial<Omit<Parameters<typeof AcquisitionShell>[0], "children">>,
  ) =>
    render(
      renderToStaticMarkup(
        <AcquisitionShell authenticated {...props}>
          <p>Content</p>
        </AcquisitionShell>,
      ),
    );

  const welcome = heading({ heroStage: "welcome" });
  expect(welcome.querySelector("h1")?.textContent).toBe("New analysis");
  expect(
    heading({ authenticated: false, welcome: true }).querySelector("h1")
      ?.textContent,
  ).toBe("New analysis");

  const processing = heading({ heroStage: "processing" });
  expect(
    processing.querySelector('[data-hero-stage="processing"] h1')?.textContent,
  ).toBe("Analysing your call");
  expect(processing.textContent).not.toMatch(/few minutes|We're processing/);

  const ready = heading({ heroStage: "ready" });
  expect(ready.querySelector('[data-hero-stage="ready"] h1')?.textContent).toBe(
    "Ready to analyse",
  );
  expect(ready.textContent).not.toContain("Analysing your call");

  const preview = heading({
    authenticated: false,
    heroStage: "processing",
    previewHero: true,
  });
  expect(preview.querySelector("h1")?.textContent).toBe(
    "Example processing state",
  );

  expect(heading({}).querySelector("h1")).toBeNull();
  expect(
    heading({ heroStage: "welcome", compactBusy: true }).querySelector("h1"),
  ).toBeNull();
});

it("shows trial minutes only from a verified allowance", () => {
  const without = render(
    renderToStaticMarkup(
      <AcquisitionShell authenticated>
        <p>Content</p>
      </AcquisitionShell>,
    ),
  );
  expect(without.querySelector("[data-minutes-meter]")).toBeNull();

  const shell = render(
    renderToStaticMarkup(
      <AcquisitionShell authenticated allowance={allowance}>
        <p>Content</p>
      </AcquisitionShell>,
    ),
  );
  const meter = shell.querySelector('[role="meter"]')!;
  expect(meter.getAttribute("aria-valuenow")).toBe("2520");
  expect(meter.getAttribute("aria-valuemax")).toBe("3600");
  expect(meter.getAttribute("aria-valuetext")).toBe(
    "42 of 60 trial minutes left",
  );
  expect(shell.textContent).toContain("42 of 60 left");
  expect(shell.textContent).toContain("42 min left");
  // Owner decision (29 Sep 2026): the header ring shows the exact share of
  // the verified allowance, computed from the session read, never estimated.
  expect(shell.textContent).toContain("70%");

  const unlimited = render(
    renderToStaticMarkup(
      <AcquisitionShell
        authenticated
        allowance={{ ...allowance, available_seconds: 0, unlimited: true }}
      >
        <p>Content</p>
      </AcquisitionShell>,
    ),
  );
  expect(unlimited.querySelector('[role="meter"]')).toBeNull();
  expect(unlimited.textContent).toContain("Unlimited analysis time");
});

it("never claims privacy in the shell chrome; each saved report states it", async () => {
  const signedIn = renderToStaticMarkup(
    <AcquisitionShell authenticated>
      <p>Content</p>
    </AcquisitionShell>,
  );
  await act(async () =>
    root.render(
      <AcquisitionShell authenticated={false}>
        <p>Content</p>
      </AcquisitionShell>,
    ),
  );
  expect(signedIn).not.toContain("Private to your account");
  expect(host.textContent).not.toContain("Private to your account");
  expect(
    host
      .querySelector('a[aria-label="Profile & account"]')
      ?.getAttribute("href"),
  ).toBe("/login");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        'header button[aria-label="Open profile menu"]',
      )!
      .click(),
  );
  const menu = host.querySelector('[aria-label="Profile actions"]')!;
  expect(menu.textContent).toContain("Sign in to analyse calls");
  expect(menu.querySelector('a[href="/login"]')?.textContent).toBe("Sign in");
  expect(host.textContent).not.toContain("Private to your account");
});

it("collapses the rail from its own toggle and keeps focus on the visible toggle", async () => {
  await act(async () =>
    root.render(
      <AcquisitionShell authenticated={false}>
        <p>Content</p>
      </AcquisitionShell>,
    ),
  );
  const toggle = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Collapse sidebar navigation"]',
  )!;
  const panel = document.getElementById(toggle.getAttribute("aria-controls")!)!;
  expect(panel).not.toBeNull();
  expect(panel.contains(toggle)).toBe(true);
  expect(panel.hasAttribute("inert")).toBe(false);
  toggle.focus();
  expect.soft(toggle.getAttribute("aria-expanded")).toBe("true");
  await act(async () => toggle.click());
  expect(host.querySelector('[data-sidebar-collapsed="true"]')).not.toBeNull();
  expect(localStorage.getItem("sx.sidebar.collapsed")).toBe("true");
  const expand = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Expand sidebar navigation"]',
  )!;
  expect(expand).not.toBeNull();
  // DOM coverage of the native keyboard exclusion; browser Tab proof is separate.
  expect(panel.hasAttribute("inert")).toBe(true);
  expect(panel.querySelector('a[href="/analysis/calls"]')).not.toBeNull();
  expect(expand.getAttribute("aria-controls")).toBe(panel.id);
  expect(expand.closest("[inert]")).toBeNull();
  expect.soft(expand.getAttribute("aria-expanded")).toBe("false");
  expect.soft(document.activeElement).toBe(expand);
  expand.focus();
  await act(async () => expand.click());
  expect(host.querySelector('[data-sidebar-collapsed="false"]')).not.toBeNull();
  expect(localStorage.getItem("sx.sidebar.collapsed")).toBe("false");
  expect(panel.hasAttribute("inert")).toBe(false);
  expect.soft(document.activeElement).toBe(toggle);
});

it("offers the theme control in the account menu only when the theme is released", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  );
  const openMenu = async () => {
    const trigger = host.querySelector<HTMLButtonElement>(
      'header button[aria-label="Open profile menu"]',
    )!;
    await act(async () => trigger.click());
    const menu = host.querySelector(
      '[role="region"][aria-label="Profile actions"]',
    );
    expect(menu).not.toBeNull();
    return menu!;
  };

  await act(async () =>
    root.render(
      <AcquisitionShell authenticated={false}>
        <p>Content</p>
      </AcquisitionShell>,
    ),
  );
  expect((await openMenu())?.querySelector("fieldset")).toBeNull();

  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ThemeProvider controlEnabled>
        <AcquisitionShell authenticated={false}>
          <p>Content</p>
        </AcquisitionShell>
      </ThemeProvider>,
    ),
  );
  const menu = await openMenu();
  expect(menu?.querySelector("legend")?.textContent).toBe("Theme");
  expect(
    [...(menu?.querySelectorAll('input[type="radio"]') ?? [])].map(
      (input) => (input as HTMLInputElement).value,
    ),
  ).toEqual(["system", "light", "dark"]);
});
