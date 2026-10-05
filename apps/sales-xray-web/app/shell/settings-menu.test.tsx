import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { SettingsMenu } from "./settings-menu";
import type { Allowance } from "../acquisition-client";
import { guideOffKey } from "../guide-progress";
import { FIRST_CALL_GUIDE } from "../guide-registry";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "../workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let originalWidth: number | null = null;
let originalHeight: number | null = null;

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  if (originalWidth !== null)
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: originalWidth,
    });
  if (originalHeight !== null)
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: originalHeight,
    });
  originalWidth = null;
  originalHeight = null;
});

it("keeps the account menu inside the mobile viewport by the active trigger", async () => {
  originalWidth = window.innerWidth;
  originalHeight = window.innerHeight;
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 390,
  });
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    value: 800,
  });

  const anchor = document.createElement("a");
  anchor.getBoundingClientRect = () =>
    ({
      left: 150,
      right: 230,
      top: 740,
      bottom: 780,
      width: 80,
      height: 40,
    }) as DOMRect;
  const anchorRef = { current: anchor };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <SettingsMenu
        open
        anchorRef={anchorRef}
        onClose={() => {}}
        name="Fictional User"
        email="fictional@example.test"
        allowance={null}
      />,
    ),
  );

  const menu = document.querySelector<HTMLElement>(
    '[role="dialog"][aria-label="Account menu"]',
  )!;
  expect(menu.style.left).toBe("45px");
  expect(Number.parseFloat(menu.style.bottom)).toBeGreaterThan(0);
  expect(Number.parseFloat(menu.style.bottom)).toBeLessThan(800);
});

it.each<[Allowance, string | null]>([
  [
    {
      allowance_seconds: 600000,
      available_seconds: 600000,
      committed_seconds: 0,
    },
    "166 h of 166 h left",
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
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <SettingsMenu
        open
        anchorRef={{ current: document.createElement("button") }}
        onClose={() => {}}
        name="Fictional User"
        email="fictional@example.test"
        allowance={allowance}
      />,
    ),
  );
  const menu = document.querySelector(
    '[role="dialog"][aria-label="Account menu"]',
  )!;
  if (text) expect(menu.textContent).toContain(text);
  expect(menu.textContent).not.toMatch(/Unlimited|unavailable|Trial/i);
  expect(menu.querySelector('a[href="/plans"]')?.textContent).toBe("Plans");
  if (allowance.unlimited) {
    expect(menu.querySelector('[aria-hidden="true"] i')).toBeNull();
    const buttons = [...menu.querySelectorAll("button")];
    expect(
      buttons.some((button) => button.textContent?.includes("Analysis time")),
    ).toBe(false);
    expect(
      buttons.find((button) => button.textContent?.startsWith("Usage"))
        ?.textContent,
    ).toBe("Usage");
  }
});

it("switches the first-call guide off and back on from the account menu", async () => {
  localStorage.clear();
  const access: WorkspaceAccessValue = {
    status: "ready",
    authenticated: true,
    context: { personId: "fictional-a", sessionId: "s", tenantId: "t" },
    retry: () => {},
  };
  const onClose = vi.fn();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access}>
        <SettingsMenu
          open
          anchorRef={{ current: document.createElement("button") }}
          onClose={onClose}
          name="Fictional User"
          email="fictional@example.test"
          allowance={null}
        />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  const toggle = document.querySelector<HTMLButtonElement>('[role="switch"]')!;
  expect(toggle.textContent).toContain("First call guide");
  expect(toggle.getAttribute("aria-checked")).toBe("true");
  await act(async () => toggle.click());
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  expect(toggle.textContent).toContain("Off");
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

it("has no guide switch without a signed-in person", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <SettingsMenu
        open
        anchorRef={{ current: document.createElement("button") }}
        onClose={() => {}}
        name={null}
        email={null}
        allowance={null}
      />,
    ),
  );
  expect(document.querySelector('[role="switch"]')).toBeNull();
});
