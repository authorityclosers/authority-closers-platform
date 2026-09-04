import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  CommandPalette,
  getDefaultCommandPaletteItems,
  resolveCommandPaletteRestoreFocusTarget,
  MobileBottomNav,
  MobileMoreSheet,
  SidebarBadge,
  SidebarCollapseButton,
  SidebarNav,
  SidebarNavItem,
  SidebarTooltip,
  TenantIdentity,
  TenantSwitcher,
  type SidebarNavItemConfig,
  type SidebarNavSection,
  type TenantIdentityConfig,
  type TenantInfo,
} from "./index";
import {
  DEFAULT_TENANT_IDENTITY,
  LearnerShell,
  LearnerSidebarBrand,
} from "../site-shell";
import { ROUTES } from "../../lib/routes";

describe("P1 Learner Sidebar & Navigation Architecture", () => {
  describe("Brand hierarchy semantics", () => {
    it("renders Closers Academy as primary sidebar identity and 'by Authority Closers' as attribution", () => {
      const html = renderToStaticMarkup(
        createElement(TenantIdentity, {
          identity: DEFAULT_TENANT_IDENTITY,
          collapsed: false,
        }),
      );

      // Primary title is Closers Academy
      expect(html).toContain("Closers Academy");
      expect(html).toContain('class="tenant-identity__primary"');

      // Attribution is 'by Authority Closers'
      expect(html).toContain("by Authority Closers");
      expect(html).toContain('class="tenant-identity__attribution"');

      // Combined accessible label
      expect(html).toContain(
        'aria-label="Closers Academy — by Authority Closers"',
      );
      expect(html).toContain('href="/home"');
    });

    it("renders compact accessible mark when collapsed", () => {
      const html = renderToStaticMarkup(
        createElement(TenantIdentity, {
          identity: DEFAULT_TENANT_IDENTITY,
          collapsed: true,
        }),
      );

      expect(html).toContain("is-collapsed");
      expect(html).toContain('class="learner-sidebar-wordmark__mark"');
      expect(html).toContain(
        'aria-label="Closers Academy — by Authority Closers"',
      );
      expect(html).toContain('title="Closers Academy — by Authority Closers"');
    });

    it("renders LearnerSidebarBrand delegating to TenantIdentity with founder-confirmed defaults", () => {
      const html = renderToStaticMarkup(
        createElement(LearnerSidebarBrand, { collapsed: false }),
      );

      expect(html).toContain("Closers Academy");
      expect(html).toContain("by Authority Closers");
      expect(html).toContain('class="learner-sidebar-wordmark__mark"');
    });
  });

  describe("Generic primitives and configuration", () => {
    it("renders custom configured brand identities without hard-coded brand names", () => {
      const customIdentity: TenantIdentityConfig = {
        tenantName: "Northstar Enterprise",
        academyName: "Northstar Academy",
        attribution: "by Northstar Enterprise",
        homeHref: "/dashboard/custom",
        mark: createElement("span", { className: "custom-mark" }, "NE"),
      };

      const html = renderToStaticMarkup(
        createElement(TenantIdentity, { identity: customIdentity }),
      );

      expect(html).toContain("Northstar Academy");
      expect(html).toContain("by Northstar Enterprise");
      expect(html).toContain('href="/dashboard/custom"');
      expect(html).toContain("custom-mark");
      expect(html).not.toContain("Authority Closers");
      expect(html).not.toContain("Closers Academy");
    });

    it("renders arbitrary SidebarNav sections and items dynamically", () => {
      const customSections: SidebarNavSection[] = [
        {
          id: "custom-sec",
          label: "Specialized Track",
          items: [
            {
              id: "track-1",
              label: "Negotiation Mastery",
              href: "/tracks/negotiation",
              current: true,
            },
            {
              id: "track-2",
              label: "Discovery Sprint",
              href: "/tracks/discovery",
            },
          ],
        },
      ];

      const html = renderToStaticMarkup(
        createElement(SidebarNav, { sections: customSections }),
      );

      expect(html).toContain("Specialized Track");
      expect(html).toContain("Negotiation Mastery");
      expect(html).toContain('href="/tracks/negotiation"');
      expect(html).toContain("Discovery Sprint");
      expect(html).toContain('href="/tracks/discovery"');
    });
  });

  describe("Conditional Tenant Switcher", () => {
    it("hides and renders nothing when only one tenant is configured (no fake switcher)", () => {
      const singleTenant: TenantInfo[] = [
        { id: "tenant-1", name: "Authority Closers" },
      ];

      const html = renderToStaticMarkup(
        createElement(TenantSwitcher, {
          currentTenantId: "tenant-1",
          tenants: singleTenant,
        }),
      );

      expect(html).toBe("");
      expect(html).not.toContain("tenant-switcher");
      expect(html).not.toContain("button");
    });

    it("hides and renders nothing when tenants list is empty or undefined", () => {
      expect(
        renderToStaticMarkup(createElement(TenantSwitcher, { tenants: [] })),
      ).toBe("");

      expect(
        renderToStaticMarkup(
          createElement(TenantSwitcher, { tenants: undefined }),
        ),
      ).toBe("");
    });

    it("does not expose a no-op switcher when multiple tenants lack an authorized handler", () => {
      const multiTenants: TenantInfo[] = [
        { id: "t1", name: "Authority Closers" },
        { id: "t2", name: "Partner Sales Org" },
      ];

      const html = renderToStaticMarkup(
        createElement(TenantSwitcher, {
          currentTenantId: "t1",
          tenants: multiTenants,
        }),
      );

      expect(html).toBe("");
      expect(html).not.toContain("tenant-switcher");
      expect(html).not.toContain('aria-haspopup="menu"');
    });

    it("renders an accessible switcher only when a real selection handler exists", () => {
      const multiTenants: TenantInfo[] = [
        { id: "t1", name: "Authority Closers" },
        { id: "t2", name: "Partner Sales Org" },
      ];

      const html = renderToStaticMarkup(
        createElement(TenantSwitcher, {
          currentTenantId: "t1",
          tenants: multiTenants,
          onSelectTenant: vi.fn(),
        }),
      );

      expect(html).toContain('class="tenant-switcher"');
      expect(html).toContain('aria-haspopup="menu"');
      expect(html).toContain('aria-expanded="false"');
      expect(html).toContain("Authority Closers");
      expect(html).toContain("AC"); // initials
    });
  });

  describe("Sidebar badges & data integrity", () => {
    it("never fabricates badge data when badge is omitted or count is 0", () => {
      expect(renderToStaticMarkup(createElement(SidebarBadge))).toBe("");
      expect(
        renderToStaticMarkup(
          createElement(SidebarBadge, {
            badge: { variant: "count", count: 0 },
          }),
        ),
      ).toBe("");
    });

    it("renders dot variant with screen reader description", () => {
      const html = renderToStaticMarkup(
        createElement(SidebarBadge, {
          badge: { variant: "dot", label: "New update available" },
        }),
      );

      expect(html).toContain("sidebar-badge--dot");
      expect(html).toContain(
        'sidebar-badge sidebar-badge--dot" aria-hidden="true"></span><span class="sr-only">',
      );
      expect(html).not.toContain('aria-hidden="true"><span class="sr-only">');
      expect(html).toContain("New update available");
    });

    it("renders count variant with proper numeric limits", () => {
      const normalCount = renderToStaticMarkup(
        createElement(SidebarBadge, {
          badge: { variant: "count", count: 7 },
        }),
      );
      expect(normalCount).toContain("sidebar-badge--count");
      expect(normalCount).toContain("7");
      expect(normalCount).toContain('aria-label="7 unread"');

      const highCount = renderToStaticMarkup(
        createElement(SidebarBadge, {
          badge: { variant: "count", count: 120 },
        }),
      );
      expect(highCount).toContain("99+");
    });

    it("renders 'new' variant badge", () => {
      const html = renderToStaticMarkup(
        createElement(SidebarBadge, {
          badge: { variant: "new", label: "Beta feature" },
        }),
      );

      expect(html).toContain("sidebar-badge--new");
      expect(html).toContain("New");
      expect(html).toContain('aria-label="Beta feature"');
    });

    it("renders real progress variant with percentage clamp and track fill", () => {
      const html = renderToStaticMarkup(
        createElement(SidebarBadge, {
          badge: { variant: "progress", progress: 68 },
        }),
      );

      expect(html).toContain("sidebar-badge--progress");
      expect(html).toContain("68%");
      expect(html).toContain("width:68%");
    });
  });

  describe("Nested navigation & grounded Learning links", () => {
    it("renders grounded nested children under Learning with compact 38px rows", () => {
      const learningItem: SidebarNavItemConfig = {
        id: "learning",
        label: "My Learning",
        href: ROUTES.learning,
        current: true,
        children: [
          {
            id: "current-course",
            label: "Enterprise Sales Sprint",
            href: "/learn/enterprise-sales-sprint",
            current: true,
          },
          {
            id: "catalog-all",
            label: "All Enrolled Modules",
            href: "/learning#modules",
          },
        ],
      };

      const html = renderToStaticMarkup(
        createElement(SidebarNavItem, {
          item: learningItem,
          collapsed: false,
        }),
      );

      expect(html).toContain("has-children");
      expect(html).toContain('class="sidebar-nav__sublist"');
      expect(html).toContain("Enterprise Sales Sprint");
      expect(html).toContain('href="/learn/enterprise-sales-sprint"');
      expect(html).toContain("All Enrolled Modules");
      expect(html).toContain('href="/learning#modules"');
      expect(html).toContain("sidebar-nav-item--compact");
    });

    it("hides nested sublist when sidebar is collapsed to keep rail clean and zero-jump", () => {
      const learningItem: SidebarNavItemConfig = {
        id: "learning",
        label: "My Learning",
        href: ROUTES.learning,
        children: [
          {
            id: "sub-1",
            label: "Module 1",
            href: "/learn/course/module-1",
          },
        ],
      };

      const html = renderToStaticMarkup(
        createElement(SidebarNavItem, {
          item: learningItem,
          collapsed: true,
        }),
      );

      expect(html).not.toContain('class="sidebar-nav__sublist"');
      expect(html).not.toContain("Module 1");
    });
  });

  describe("Disabled nav items and reasons", () => {
    it("renders disabled items with aria-disabled, tabIndex -1, and screen reader reason", () => {
      const disabledItem: SidebarNavItemConfig = {
        id: "adv-cert",
        label: "Executive Certification",
        href: "/certificates/executive",
        disabled: true,
        disabledReason: "Prerequisite modules required",
      };

      const html = renderToStaticMarkup(
        createElement(SidebarNavItem, {
          item: disabledItem,
          collapsed: false,
        }),
      );

      expect(html).toContain('aria-disabled="true"');
      expect(html).toContain('tabindex="-1"');
      expect(html).toContain("is-disabled");
      expect(html).toContain("Prerequisite modules required");
    });
  });

  describe("Accessible tooltips in collapsed mode", () => {
    it("renders trigger directly when active is false (expanded mode)", () => {
      const html = renderToStaticMarkup(
        createElement(
          SidebarTooltip,
          { content: "Dashboard", active: false },
          createElement("a", { href: "/home" }, "Dashboard"),
        ),
      );

      expect(html).toContain('href="/home"');
      expect(html).not.toContain('role="tooltip"');
    });

    it("associates aria-describedby with tooltip id when active is true (collapsed mode)", () => {
      const html = renderToStaticMarkup(
        createElement(
          SidebarTooltip,
          { content: "Dashboard", active: true },
          createElement("a", { href: "/home" }, "Icon"),
        ),
      );

      expect(html).toContain('class="sidebar-tooltip-wrapper"');
      expect(html).toContain("aria-describedby");
    });
  });

  describe("SidebarCollapseButton rail toggle", () => {
    it("renders with exact learner-sidebar-toggle class, aria-expanded, and accessible title", () => {
      const expandedHtml = renderToStaticMarkup(
        createElement(SidebarCollapseButton, {
          collapsed: false,
          onToggle: vi.fn(),
        }),
      );
      expect(expandedHtml).toContain('class="learner-sidebar-toggle"');
      expect(expandedHtml).toContain('aria-expanded="true"');
      expect(expandedHtml).toContain('title="Collapse sidebar"');

      const collapsedHtml = renderToStaticMarkup(
        createElement(SidebarCollapseButton, {
          collapsed: true,
          onToggle: vi.fn(),
        }),
      );
      expect(collapsedHtml).toContain('aria-expanded="false"');
      expect(collapsedHtml).toContain('title="Expand sidebar"');
    });
  });

  describe("Command Palette and keyboard navigation", () => {
    it("renders null when closed", () => {
      const html = renderToStaticMarkup(
        createElement(CommandPalette, {
          open: false,
          onClose: vi.fn(),
        }),
      );

      expect(html).toBe("");
    });

    it("renders accessible modal with search input, default items, and keyboard shortcut hints when open", () => {
      const html = renderToStaticMarkup(
        createElement(CommandPalette, {
          open: true,
          onClose: vi.fn(),
          learningHref: "/learning",
        }),
      );

      expect(html).toContain('role="dialog"');
      expect(html).toContain('aria-modal="true"');
      expect(html).toContain('class="command-palette-input"');
      expect(html).toContain("Dashboard");
      expect(html).toContain("My Learning");
      expect(html).toContain("Discover");
      expect(html).toContain("Progress");
      expect(html).toContain("Settings &amp; Appearance");
      expect(html).toContain("quick jump");
    });

    it("getDefaultCommandPaletteItems returns grounded routes with shortcuts", () => {
      const items = getDefaultCommandPaletteItems("/learning");
      expect(items.find((i) => i.id === "nav-dashboard")?.shortcut).toBe("G H");
      expect(items.find((i) => i.id === "nav-learning")?.shortcut).toBe("G L");
      expect(items.find((i) => i.id === "nav-settings")?.href).toBe(
        "/settings",
      );
    });

    it("restores focus to actual invoking element for both sidebar and header search triggers", () => {
      const sidebarSearchBtn = { id: "sidebar-search-btn" } as HTMLElement;
      const headerSearchLink = { id: "header-search-link" } as HTMLElement;

      // 1. Sidebar trigger path: restores to sidebar button even when header searchTriggerRef is provided
      const sidebarTarget = resolveCommandPaletteRestoreFocusTarget({
        invokingElement: sidebarSearchBtn,
        fallbackTrigger: headerSearchLink,
      });
      expect(sidebarTarget).toBe(sidebarSearchBtn);

      // 2. Top-header trigger path: restores to header search link
      const headerTarget = resolveCommandPaletteRestoreFocusTarget({
        invokingElement: headerSearchLink,
        fallbackTrigger: headerSearchLink,
      });
      expect(headerTarget).toBe(headerSearchLink);

      // 3. Shortcut path (Ctrl/Cmd+K): restores to the previously active element if one was focused
      const activeNavElement = { id: "dashboard-link" } as HTMLElement;
      const shortcutTargetWithActive = resolveCommandPaletteRestoreFocusTarget({
        activeElement: activeNavElement,
        fallbackTrigger: headerSearchLink,
      });
      expect(shortcutTargetWithActive).toBe(activeNavElement);

      // 4. Shortcut path (Ctrl/Cmd+K): falls back to top header search if no specific element was focused
      const shortcutTargetFallback = resolveCommandPaletteRestoreFocusTarget({
        activeElement: null,
        fallbackTrigger: headerSearchLink,
      });
      expect(shortcutTargetFallback).toBe(headerSearchLink);
    });
  });

  describe("Mobile bottom navigation & More drawer", () => {
    it("renders the 5-item mobile bottom navigation bar", () => {
      const html = renderToStaticMarkup(
        createElement(MobileBottomNav, {
          current: "dashboard",
          moreOpen: false,
          onToggleMore: vi.fn(),
          moreButtonRef: { current: null },
        }),
      );

      expect(html).toContain('class="learner-bottom-nav"');
      expect(html).toContain('aria-label="Learner mobile navigation"');
      expect(html).toContain("Home");
      expect(html).toContain("Learning");
      expect(html).toContain("Discover");
      expect(html).toContain("Progress");
      expect(html).toContain("More");
    });

    it("marks More as the current mobile destination for Calendar", () => {
      const html = renderToStaticMarkup(
        createElement(MobileBottomNav, {
          current: "calendar",
          moreOpen: false,
          onToggleMore: vi.fn(),
          moreButtonRef: { current: null },
        }),
      );

      expect(html).toContain(
        'class="learner-nav__link is-current" aria-expanded="false" aria-controls="learner-more-drawer" aria-current="page"',
      );
    });

    it("renders accessible More sheet modal dialog when open", () => {
      const html = renderToStaticMarkup(
        createElement(MobileMoreSheet, {
          open: true,
          onClose: vi.fn(),
          userDisplayName: "Alex",
        }),
      );

      expect(html).toContain('id="learner-more-drawer"');
      expect(html).toContain('role="dialog"');
      expect(html).toContain('aria-modal="true"');
      expect(html).toContain("Alex");
      expect(html).toContain("Profile &amp; Identity");
      expect(html).toContain("Notifications");
      expect(html).toContain("Settings &amp; Appearance");
    });
  });

  describe("CSS layout tokens & reduced-motion fidelity", () => {
    it("contains 252px/64px sidebar dimensions, 44px/38px row heights, and 80/140/220/320ms timing tokens", () => {
      const css = readFileSync(
        new URL("../../learner-next-slice.css", import.meta.url),
        "utf8",
      );

      expect(css).toContain("--sidebar-width-expanded: 252px;");
      expect(css).toContain("--sidebar-width-collapsed: 64px;");
      expect(css).toContain("--sidebar-row-comfortable: 44px;");
      expect(css).toContain("--sidebar-row-compact: 38px;");
      expect(css).toContain("--sidebar-duration-instant: 80ms;");
      expect(css).toContain("--sidebar-duration-fast: 140ms;");
      expect(css).toContain("--sidebar-duration-normal: 220ms;");
      expect(css).toContain("--sidebar-duration-slow: 320ms;");
      expect(css).toContain("--sidebar-active-rail-width: 2px;");
      expect(css).toContain(
        ".site-frame--learner.site-frame--collapsed .learner-header",
      );
      expect(css).toContain(
        ".site-frame--learner.site-frame--collapsed .learner-main",
      );
      expect(css).toContain("margin-left: 0 !important;");
      expect(css).toContain(".site-frame--learner .mobile-drawer-overlay");
      expect(css).toContain("z-index: 160;");
    });

    it("uses the approved shared BrandMark instead of a handcrafted academy SVG", () => {
      const identitySource = readFileSync(
        new URL("./tenant-identity.tsx", import.meta.url),
        "utf8",
      );
      const shellSource = readFileSync(
        new URL("../site-shell.tsx", import.meta.url),
        "utf8",
      );

      expect(identitySource).not.toContain("function ClosersAcademyMark");
      expect(identitySource).not.toContain("<svg");
      expect(shellSource).toContain(
        'mark: <BrandMark className="learner-sidebar-wordmark__mark-art" />',
      );
    });

    it("enforces subtle active tint + 2px rail, neutral hover, scale .985 press, and 2px focus ring", () => {
      const css = readFileSync(
        new URL("../../learner-next-slice.css", import.meta.url),
        "utf8",
      );

      expect(css).toContain(".sidebar-nav-item.is-current");
      expect(css).toContain("border-left-color: var(--sidebar-rail-accent);");
      expect(css).toContain(
        ".sidebar-nav-item:hover:not(.is-current):not(.is-disabled)",
      );
      expect(css).toContain(".sidebar-nav-item:active:not(.is-disabled)");
      expect(css).toContain("transform: scale(0.985);");
      expect(css).toContain("outline: var(--sidebar-focus-ring-width)");
    });

    it("disables transitions and animations under prefers-reduced-motion", () => {
      const css = readFileSync(
        new URL("../../learner-next-slice.css", import.meta.url),
        "utf8",
      );

      expect(css).toContain("@media (prefers-reduced-motion: reduce)");
      expect(css).toContain(".site-frame--learner .learner-sidebar");
      expect(css).toContain(".site-frame--learner .sidebar-nav-item");
      expect(css).toContain(".site-frame--learner .command-palette-dialog");
      expect(css).toContain("transition: none !important;");
      expect(css).toContain("animation: none !important;");
      expect(css).toContain("transform: none !important;");
    });
  });

  describe("LearnerShell integrated prototype", () => {
    it("renders full workspace and account sections with tenant identity", () => {
      const html = renderToStaticMarkup(
        createElement(LearnerShell, {
          current: "dashboard",
          userDisplayName: "Alex Mercer",
        }),
      );

      // Identity & Brand
      expect(html).toContain("Closers Academy");
      expect(html).toContain("by Authority Closers");

      // Workspace & Account items
      expect(html).toContain("Dashboard");
      expect(html).toContain("My Learning");
      expect(html).toContain("Discover");
      expect(html).toContain("Progress");
      expect(html).toContain("Notifications");
      expect(html).toContain("Profile");
      expect(html).toContain("Settings");
      expect(html).toContain("Help");

      // No fake switcher with 1 default tenant
      expect(html).not.toContain("Switch organization");

      // Mobile nav
      expect(html).toContain('class="learner-bottom-nav"');

      // Sidebar search trigger with Cmd+K
      expect(html).toContain('class="learner-sidebar__search-trigger"');
      expect(html).toContain("⌘K");

      // Anchored account/profile footer with real user information
      expect(html).toContain('class="learner-sidebar__footer"');
      expect(html).toContain('class="learner-sidebar__account"');
      expect(html).toContain("Alex Mercer");

      // Redundant Dashboard context label removed from top header
      expect(html).not.toContain('class="learner-header__context"');
    });

    it("ensures collapse affordance has sr-only label to prevent text overlap", () => {
      const html = renderToStaticMarkup(
        createElement(SidebarCollapseButton, {
          collapsed: false,
          onToggle: vi.fn(),
        }),
      );

      expect(html).toContain('class="sr-only learner-sidebar-toggle__label"');
      expect(html).toContain("Collapse");
    });
  });
});
