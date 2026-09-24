import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AcquisitionShell } from "./acquisition-shell";
import { ThemeProvider } from "./lightbox/theme-provider";

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
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-theme-preference");
  document.documentElement.style.colorScheme = "";
  vi.unstubAllGlobals();
});

it("keeps navigation, one main landmark and help, without placeholder chrome", () => {
  const shell = render(
    renderToStaticMarkup(
      <AcquisitionShell authenticated heroStage="welcome">
        <p>Workspace content</p>
      </AcquisitionShell>,
    ),
  );
  expect(
    shell.querySelector('[aria-label="Sales Xray navigation"]'),
  ).not.toBeNull();
  expect(
    shell.querySelector('nav[aria-label="Workspace"] a')?.getAttribute("href"),
  ).toBe("/?new=1");
  expect(
    shell
      .querySelector('nav[aria-label="Mobile Sales Xray navigation"] a')
      ?.getAttribute("href"),
  ).toBe("/?new=1");
  expect(shell.querySelector('a[href="/calls"]')).not.toBeNull();
  expect(shell.textContent).toContain("Account & saved calls");
  expect(shell.querySelectorAll("main")).toHaveLength(1);
  expect(shell.querySelector("main")?.id).toBe("main-content");
  expect(shell.querySelector('a[href="#main-content"]')?.textContent).toBe(
    "Skip to workspace",
  );
  expect(shell.querySelector('a[aria-label="Sales Xray home"]')).not.toBeNull();

  // The former help card and footer links now live behind the "?" control.
  const help = shell.querySelector("[data-help-menu]")!;
  expect(help.querySelector('summary[aria-label="Help"]')).not.toBeNull();
  expect(help.textContent).toContain(
    "Choose a supported audio file up to 32 MB.",
  );
  const legal = help.querySelector('nav[aria-label="Legal and support"]')!;
  expect(
    [...legal.querySelectorAll("a")].map((link) => link.getAttribute("href")),
  ).toEqual([
    "https://app.authorityclosers.com/privacy",
    "https://app.authorityclosers.com/terms",
    "mailto:admin@authorityclosers.com?subject=Sales%20Xray%20help",
  ]);

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
  expect(shell.textContent).not.toMatch(/\d+%/);

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
  expect(unlimited.textContent).toContain("Unlimited testing");
});

it("claims privacy only for a signed-in account", () => {
  const signedIn = renderToStaticMarkup(
    <AcquisitionShell authenticated>
      <p>Content</p>
    </AcquisitionShell>,
  );
  const guest = renderToStaticMarkup(
    <AcquisitionShell authenticated={false}>
      <p>Content</p>
    </AcquisitionShell>,
  );
  expect(signedIn).toContain("Private to your account");
  expect(guest).not.toContain("Private to your account");
  expect(guest).toContain("Profile &amp; account");
  expect(guest).toContain("Sign in to analyse calls");
});

it("collapses the rail from its own toggle and keeps focus on it", async () => {
  await act(async () =>
    root.render(
      <AcquisitionShell authenticated={false}>
        <p>Content</p>
      </AcquisitionShell>,
    ),
  );
  const toggle = host.querySelector<HTMLButtonElement>(
    '[aria-label="Collapse Sales Xray navigation"]',
  )!;
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  await act(async () => toggle.click());
  expect(toggle.getAttribute("aria-label")).toBe(
    "Expand Sales Xray navigation",
  );
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(toggle);
  expect(
    host.querySelector('[data-sidebar-collapsed="true"] aside [data-compact]'),
  ).not.toBeNull();
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
      "aside button[aria-expanded]:not([aria-controls])",
    )!;
    await act(async () => trigger.click());
    return host.querySelector('[aria-label="Profile actions"]');
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
