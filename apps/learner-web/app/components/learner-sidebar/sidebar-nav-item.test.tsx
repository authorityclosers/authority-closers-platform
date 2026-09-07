// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { registerInternalNavigationGuard } from "../../lib/local-drafts";
import { SidebarNavItem } from "./sidebar-nav-item";
import type { SidebarNavItemConfig } from "./sidebar-types";

const navigation = vi.hoisted(() => ({
  pendingHref: null as string | null,
  listeners: new Set<() => void>(),
  prefetch: vi.fn(),
  setPending(href: string | null) {
    this.pendingHref = href;
    this.listeners.forEach((listener) => listener());
  },
}));

// Router boundary stand-in: expose next/link's documented per-Link status and
// accepted-navigation callback. The component and document dirty guard are real.
// Completion and supersession are controlled by the router, never by the item.
vi.mock("next/link", async () => {
  const React = await import("react");
  const LinkStatus = React.createContext({ pending: false });
  return {
    useLinkStatus: () => React.useContext(LinkStatus),
    default: function TestLink({
      href,
      children,
      onClick,
      onNavigate,
      prefetch,
      ...props
    }: React.ComponentProps<"a"> & {
      href: string;
      prefetch?: boolean;
      onNavigate?: (event: { preventDefault: () => void }) => void;
    }) {
      const pendingHref = React.useSyncExternalStore(
        (listener) => {
          navigation.listeners.add(listener);
          return () => navigation.listeners.delete(listener);
        },
        () => navigation.pendingHref,
      );
      navigation.prefetch(href, prefetch);
      return (
        <LinkStatus.Provider value={{ pending: pendingHref === href }}>
          <a
            {...props}
            href={href}
            onClick={(event) => {
              onClick?.(event);
              if (
                event.defaultPrevented ||
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey ||
                (event.currentTarget.target &&
                  event.currentTarget.target !== "_self") ||
                new URL(href, window.location.href).origin !==
                  window.location.origin
              ) {
                return;
              }
              event.preventDefault();
              let canceled = false;
              onNavigate?.({
                preventDefault: () => {
                  canceled = true;
                },
              });
              if (!canceled) navigation.setPending(href);
            }}
          >
            {children}
          </a>
        </LinkStatus.Provider>
      );
    },
  };
});

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
let cleanupGuard: (() => void) | undefined;
const onNavigate = vi.fn();
const onItemClick = vi.fn();
const onNavigationEvent = vi.fn();
const learning: SidebarNavItemConfig = {
  id: "learning",
  label: "My learning",
  href: "/learning",
  onClick: onItemClick,
};

beforeEach(() => {
  vi.clearAllMocks();
  navigation.pendingHref = null;
  window.history.replaceState(null, "", "/home");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  window.addEventListener("ac:ui-nav-click", onNavigationEvent);
});

afterEach(async () => {
  cleanupGuard?.();
  cleanupGuard = undefined;
  await act(async () => root.unmount());
  container.remove();
  window.removeEventListener("ac:ui-nav-click", onNavigationEvent);
});

async function renderItems(...items: SidebarNavItemConfig[]) {
  await act(async () => {
    root.render(
      <ul>
        {items.map((item) => (
          <SidebarNavItem key={item.id} item={item} onNavigate={onNavigate} />
        ))}
      </ul>,
    );
  });
}

function link(href = learning.href): HTMLAnchorElement {
  const anchor = container.querySelector<HTMLAnchorElement>(
    `a[href="${href}"]`,
  );
  expect(anchor).not.toBeNull();
  return anchor!;
}

async function click(anchor = link(), options: MouseEventInit = {}) {
  const event = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    button: 0,
    ...options,
  });
  await act(async () => {
    anchor.dispatchEvent(event);
  });
  return event;
}

function expectIdle() {
  expect(container.querySelector(".is-pending")).toBeNull();
  expect(container.querySelector('[aria-busy="true"]')).toBeNull();
  expect(container.querySelector('[role="status"]')?.textContent ?? "").toBe(
    "",
  );
}

describe("sidebar navigation feedback", () => {
  it("shows router pending, then clears it on completion without remounting", async () => {
    await renderItems(learning);
    const anchor = link();
    expectIdle();
    expect(navigation.prefetch).toHaveBeenCalledWith("/learning", false);

    await click(anchor);
    expect(anchor.querySelector(".is-pending")?.getAttribute("aria-busy")).toBe(
      "true",
    );
    expect(anchor.querySelector('[role="status"]')?.textContent).toBe(
      "Opening My learning…",
    );
    expect(onNavigate).toHaveBeenCalledOnce();
    expect(onItemClick).toHaveBeenCalledOnce();
    expect(onNavigationEvent).toHaveBeenCalledOnce();

    await act(async () => navigation.setPending(null));
    expect(link()).toBe(anchor);
    expectIdle();

    // A subsequent visit can start and finish on the same mounted item.
    await click(anchor);
    expect(anchor.querySelector(".is-pending")).not.toBeNull();
    await act(async () => navigation.setPending(null));
    expectIdle();
  });

  it("clears the previous link when a second destination supersedes it", async () => {
    await renderItems(learning, {
      id: "settings",
      label: "Settings",
      href: "/settings",
    });
    await click();
    await click(link("/settings"));
    expect(link().querySelector(".is-pending")).toBeNull();
    expect(link("/settings").querySelector(".is-pending")).not.toBeNull();
    await act(async () => navigation.setPending(null));
    expectIdle();
  });

  it("does not start pending or callbacks for the exact current URL", async () => {
    window.history.replaceState(null, "", "/learning");
    await renderItems({ ...learning, current: true });
    const event = await click();
    expect(event.defaultPrevented).toBe(true);
    expect(link().getAttribute("aria-current")).toBe("page");
    expectIdle();
    expect(onNavigate).not.toHaveBeenCalled();
    expect(onItemClick).not.toHaveBeenCalled();
    expect(onNavigationEvent).not.toHaveBeenCalled();
  });

  it("allows a current section link to navigate from a different child URL", async () => {
    window.history.replaceState(null, "", "/learn/course/activity");
    await renderItems({ ...learning, current: true });
    await click();
    expect(link().getAttribute("aria-current")).toBe("page");
    expect(link().querySelector(".is-pending")).not.toBeNull();
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it.each([
    { ctrlKey: true },
    { metaKey: true },
    { shiftKey: true },
    { altKey: true },
    { button: 1 },
  ])(
    "leaves modified click %j to the browser without pending",
    async (options) => {
      await renderItems(learning);
      const event = await click(link(), options);
      expect(event.defaultPrevented).toBe(false);
      expectIdle();
      expect(onNavigate).not.toHaveBeenCalled();
      expect(onItemClick).not.toHaveBeenCalled();
      expect(onNavigationEvent).not.toHaveBeenCalled();
    },
  );

  it("never shows SPA pending for an external link", async () => {
    await renderItems({
      ...learning,
      href: "https://example.com/help",
      external: true,
    });
    await click(link("https://example.com/help"));
    expectIdle();
    expect(navigation.prefetch).not.toHaveBeenCalled();
  });

  it("preserves disabled focus, reason, and navigation semantics", async () => {
    await renderItems({
      ...learning,
      disabled: true,
      disabledReason: "Access unavailable",
    });
    const event = await click();
    expect(event.defaultPrevented).toBe(true);
    expect(link().tabIndex).toBe(-1);
    expect(link().getAttribute("aria-disabled")).toBe("true");
    expect(link().textContent).toContain("Access unavailable");
    expectIdle();
    expect(onNavigate).not.toHaveBeenCalled();
    expect(onItemClick).not.toHaveBeenCalled();
    expect(onNavigationEvent).not.toHaveBeenCalled();
  });

  it("leaves dirty-navigation cancellation authoritative and allows a later confirmed retry", async () => {
    const confirmNavigation = vi.fn().mockReturnValue(false);
    cleanupGuard = registerInternalNavigationGuard(
      document,
      true,
      confirmNavigation,
    );
    await renderItems(learning);
    const canceled = await click();
    expect(canceled.defaultPrevented).toBe(true);
    expect(confirmNavigation).toHaveBeenCalledOnce();
    expectIdle();
    expect(onNavigate).not.toHaveBeenCalled();
    expect(onItemClick).not.toHaveBeenCalled();
    expect(onNavigationEvent).not.toHaveBeenCalled();

    confirmNavigation.mockReturnValue(true);
    await click();
    expect(onNavigate).toHaveBeenCalledOnce();
    expect(link().querySelector(".is-pending")).not.toBeNull();
    await act(async () => navigation.setPending(null));
    expectIdle();
  });

  it("does not render hidden entries", async () => {
    await renderItems({ ...learning, visible: false });
    expect(container.querySelector("a")).toBeNull();
    expect(navigation.prefetch).not.toHaveBeenCalled();
  });
});
