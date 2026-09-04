// @vitest-environment happy-dom

import { act, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { CommandPalette } from "./command-palette";
import { MobileBottomNav, MobileMoreSheet } from "./mobile-navigation";
import { SidebarTooltip } from "./sidebar-tooltip";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;

async function settleEffects(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 20));
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.replaceChildren();
});

function MoreHarness() {
  const [open, setOpen] = useState(false);
  const moreButtonRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="site-frame--learner">
      <main id="mobile-test-content">
        <button type="button">Background action</button>
      </main>
      <MobileBottomNav
        current="calendar"
        moreOpen={open}
        onToggleMore={() => setOpen((current) => !current)}
        moreButtonRef={moreButtonRef}
      />
      <MobileMoreSheet
        open={open}
        onClose={() => setOpen(false)}
        userDisplayName="Learner"
        moreButtonRef={moreButtonRef}
      />
    </div>
  );
}

function PaletteHarness() {
  const [open, setOpen] = useState(false);
  const [invoker, setInvoker] = useState<HTMLElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="site-frame--learner">
      <main id="palette-test-content">
        <button
          ref={triggerRef}
          type="button"
          onClick={(event) => {
            setInvoker(event.currentTarget);
            setOpen(true);
          }}
        >
          Open search
        </button>
      </main>
      <CommandPalette
        open={open}
        onClose={() => {
          setOpen(false);
          setInvoker(null);
        }}
        invokingElement={invoker}
        triggerRef={triggerRef}
      />
    </div>
  );
}

describe("learner shell modal interactions", () => {
  it("lets MobileMoreSheet solely clean inert state and restore focus to More", async () => {
    await act(async () => root.render(<MoreHarness />));
    const moreButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="More navigation options"]',
    );
    expect(moreButton).not.toBeNull();

    await act(async () => moreButton?.click());
    await settleEffects();

    const shell = container.querySelector<HTMLElement>(".site-frame--learner");
    const overlay = shell?.querySelector<HTMLElement>(".mobile-drawer-overlay");
    expect(overlay).not.toBeNull();
    expect(
      Array.from(shell?.children ?? []).filter(
        (element) => element !== overlay && element.hasAttribute("inert"),
      ).length,
    ).toBeGreaterThan(0);

    const closeButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Close menu"]',
    );
    await act(async () => closeButton?.click());
    await settleEffects();

    expect(container.querySelector(".mobile-drawer-overlay")).toBeNull();
    expect(
      Array.from(shell?.children ?? []).filter((element) =>
        element.hasAttribute("inert"),
      ),
    ).toHaveLength(0);
    expect(document.activeElement).toBe(moreButton);
  });

  it("gives the command palette a stable title, traps Tab, cleans inert, and restores its invoker", async () => {
    await act(async () => root.render(<PaletteHarness />));
    const trigger = container.querySelector<HTMLButtonElement>("main button");
    await act(async () => trigger?.click());
    await settleEffects();

    const dialog = container.querySelector<HTMLElement>('[role="dialog"]');
    const titleId = dialog?.getAttribute("aria-labelledby");
    const title = titleId ? document.getElementById(titleId) : null;
    const input = dialog?.querySelector<HTMLInputElement>("input");
    const listbox = dialog?.querySelector<HTMLElement>('[role="listbox"]');
    const selectedOption = dialog?.querySelector<HTMLElement>(
      '[role="option"][aria-selected="true"]',
    );
    expect(title?.tagName).toBe("H2");
    expect(title?.textContent).toContain("Search and navigate");
    expect(input?.id).not.toBe(titleId);
    expect(input?.getAttribute("role")).toBe("combobox");
    expect(input?.getAttribute("aria-controls")).toBe(listbox?.id);
    expect(input?.getAttribute("aria-expanded")).toBe("true");
    expect(input?.getAttribute("aria-autocomplete")).toBe("list");
    expect(input?.getAttribute("aria-activedescendant")).toBe(
      selectedOption?.id,
    );
    expect(document.activeElement).toBe(input);

    await act(async () => {
      input?.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "ArrowDown",
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    const nextSelectedOption = dialog?.querySelector<HTMLElement>(
      '[role="option"][aria-selected="true"]',
    );
    expect(nextSelectedOption?.id).not.toBe(selectedOption?.id);
    expect(input?.getAttribute("aria-activedescendant")).toBe(
      nextSelectedOption?.id,
    );

    const tab = new KeyboardEvent("keydown", {
      key: "Tab",
      bubbles: true,
      cancelable: true,
    });
    document.dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);

    const reverseTab = new KeyboardEvent("keydown", {
      key: "Tab",
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    document.dispatchEvent(reverseTab);
    expect(reverseTab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);

    const escape = new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    });
    await act(async () => document.dispatchEvent(escape));
    await settleEffects();

    const shell = container.querySelector<HTMLElement>(".site-frame--learner");
    expect(container.querySelector(".command-palette-overlay")).toBeNull();
    expect(
      Array.from(shell?.children ?? []).filter((element) =>
        element.hasAttribute("inert"),
      ),
    ).toHaveLength(0);
    expect(document.activeElement).toBe(trigger);
  });

  it("renders tooltip in document.body via portal with role=tooltip and aria-describedby when active in collapsed mode", async () => {
    function TooltipHarness() {
      return (
        <div className="site-frame--learner site-frame--collapsed">
          <aside className="learner-sidebar">
            <SidebarTooltip content="Dashboard" active={true}>
              <a href="/home" id="dashboard-nav-item">
                Dashboard icon
              </a>
            </SidebarTooltip>
          </aside>
        </div>
      );
    }

    await act(async () => root.render(<TooltipHarness />));
    const trigger = container.querySelector<HTMLAnchorElement>(
      "#dashboard-nav-item",
    );
    expect(trigger).not.toBeNull();

    // Trigger hover or focus
    await act(async () => {
      trigger?.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      trigger?.focus();
    });
    await settleEffects();

    const tooltip = document.body.querySelector<HTMLElement>('[role="tooltip"]');
    expect(tooltip).not.toBeNull();
    expect(tooltip?.textContent).toContain("Dashboard");
    expect(trigger?.getAttribute("aria-describedby")).toBe(tooltip?.id);

    // Blur cleans up
    await act(async () => {
      trigger?.blur();
      trigger?.dispatchEvent(new MouseEvent("mouseout", { bubbles: true }));
    });
    await settleEffects();

    expect(document.body.querySelector('[role="tooltip"]')).toBeNull();
  });
});
