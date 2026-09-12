import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  AppShell,
  closeAccountMenu,
  closeNotificationPopover,
  initialsForDisplayName,
  LearnerShell,
  MobileLearnerBrand,
} from "../components/site-shell";
import {
  firstActionableActivity,
  loadDashboardData,
  presentationModuleTitle,
} from "../components/dashboard-runtime";
import {
  DiscoverRuntime,
  loadDiscoverData,
} from "../components/discover-runtime";
import { LearningActivityNavigation } from "../components/learner-runtime";
import { loadLearningData } from "../components/learning-runtime";
import { NotificationsRuntime } from "../components/notifications-runtime";
import { loadProfileData } from "../components/profile-runtime";
import { loadProgressData } from "../components/progress-runtime";
import { startSettingsResourceLoad } from "../components/settings-runtime";
import { isActivityActionable } from "../components/learning-runtime";
import { SignOutControl } from "../components/sign-out-control";
import {
  DashboardSkeleton,
  DiscoverSkeleton,
  LearningSkeleton,
  NotificationsSkeleton,
  ProfileSkeleton,
  ProgressSkeleton,
  SettingsSkeleton,
} from "../components/skeletons";
import {
  normalizeThemePreference,
  resolveThemePreference,
} from "../components/theme-control";
import DiscoverPage from "../discover/page";
import DashboardPage from "../home/page";
import LearningPage from "../learning/page";
import NotificationsPage from "../notifications/page";
import ProfilePage from "../profile/page";
import ProgressPage from "../progress/page";
import SettingsPage from "../settings/page";
import {
  ApiError,
  createLearnerApi,
  type LearnerApi,
  type CalendarResponse,
  type LearningCollectionResponse,
  type LearningResponse,
  type MeResponse,
  type ProgramSummaryResponse,
} from "./learner-api";
import { ROUTES } from "./routes";
import { markOfflineRead } from "./offline-read-cache";

describe("Direction A & B UI System & Shell", () => {
  const me: MeResponse = {
    person_id: "person-1",
    email: "learner@example.com",
    display_name: "Learner",
    email_verified_at: "2026-09-01T00:00:00Z",
    selected_tenant_id: null,
    membership_role: "learner",
    permissions: [],
  };
  const freeCourse: ProgramSummaryResponse = {
    id: "program-1",
    slug: "authority-closers-free-course",
    title: "Published course",
    program_version_id: "version-1",
    version_number: 1,
    published_at: "2026-09-01T00:00:00Z",
  };
  const learning: LearningResponse = {
    program_id: "program-1",
    program_version_id: "version-1",
    program_slug: freeCourse.slug,
    program_title: freeCourse.title,
    version_number: 1,
    enrollment_id: "enrollment-1",
    modules: [
      {
        id: "module-1",
        position: 1,
        title: "Published module",
        activities: [
          {
            id: "locked",
            module_id: "module-1",
            program_version_id: "version-1",
            position: 1,
            kind: "REFLECTION",
            title: "Locked activity",
            prompt: null,
            state: "locked",
            revision: 1,
            required: true,
            explanation: {
              activity_id: "locked",
              state: "locked",
              required: true,
              reason: "A prerequisite is incomplete.",
              missing_activity_ids: ["available"],
              missing_module_ids: [],
            },
            allowed_actions: [],
          },
          {
            id: "awaiting",
            module_id: "module-1",
            program_version_id: "version-1",
            position: 2,
            kind: "REVIEW",
            title: "Awaiting activity",
            prompt: null,
            state: "awaiting_review",
            revision: 1,
            required: true,
            explanation: {
              activity_id: "awaiting",
              state: "awaiting_review",
              required: true,
              reason: "Review is pending.",
              missing_activity_ids: [],
              missing_module_ids: [],
            },
            allowed_actions: [],
          },
          {
            id: "available",
            module_id: "module-1",
            program_version_id: "version-1",
            position: 3,
            kind: "REFLECTION",
            title: "Available activity",
            prompt: "Reflect.",
            state: "available",
            revision: 1,
            required: true,
            explanation: {
              activity_id: "available",
              state: "available",
              required: true,
              reason: "Ready.",
              missing_activity_ids: [],
              missing_module_ids: [],
            },
            allowed_actions: ["save_draft"],
          },
        ],
      },
    ],
    projection: {
      scope_type: "course",
      scope_id: "program-1",
      program_version: "1",
      projection_version: "1",
      denominator: 3,
      completed_count: 0,
      percentage: 0,
      predicate: "required activities",
      missing_module_ids: [],
      activity_reasons: [],
    },
  };
  const learningCollection: LearningCollectionResponse = {
    items: [
      {
        program_id: learning.program_id,
        program_version_id: learning.program_version_id,
        program_slug: learning.program_slug,
        program_title: learning.program_title,
        version_number: learning.version_number,
        enrollment_id: learning.enrollment_id,
        enrolled_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
        state: "in_progress",
        saved_state: "unavailable",
        projection: learning.projection,
      },
    ],
    next_cursor: null,
    saved_filter_available: false,
  };
  const calendar: CalendarResponse = {
    source: "explicit_learning_plan",
    disclaimer: "Only explicitly published learning-plan items are shown.",
    periods: {
      today: {
        period: "today",
        status: "available",
        source: "explicit_learning_plan",
        message: null,
        items: [
          {
            id: "plan-1",
            tenant_id: "tenant-1",
            person_id: me.person_id,
            period: "today",
            title: "Complete the published activity",
            activity_id: "available",
            planned_for: null,
            state: "planned",
            source: "explicit_learning_plan",
          },
        ],
      },
      week: {
        period: "week",
        status: "not_configured",
        source: "explicit_learning_plan",
        message: "No weekly plan is published.",
        items: [],
      },
      month: {
        period: "month",
        status: "not_configured",
        source: "explicit_learning_plan",
        message: "No monthly plan is published.",
        items: [],
      },
    },
  };

  function apiFor(overrides: Partial<LearnerApi> = {}): LearnerApi {
    return {
      me: vi.fn(async () => me),
      onboarding: vi.fn(async () => ({
        person_id: me.person_id,
        experience_context: null,
        learning_goal: null,
        practice_situation: null,
        weekly_minutes: null,
        status: "completed" as const,
        current_step: 0,
        revision: 1,
        updated_at: "2026-09-01T00:00:00Z",
        next_action_href: "/home",
        next_action_reason: "complete",
      })),
      listPrograms: vi.fn(async () => ({
        items: [freeCourse],
        next_cursor: null,
      })),
      learningCollection: vi.fn(async () => learningCollection),
      learning: vi.fn(async () => learning),
      ...overrides,
    } as LearnerApi;
  }

  describe("Theme light-default behavior", () => {
    it("defaults to light when no preference or invalid value is stored", () => {
      expect(normalizeThemePreference(null)).toBe("light");
      expect(normalizeThemePreference(undefined)).toBe("light");
      expect(normalizeThemePreference("")).toBe("light");
      expect(normalizeThemePreference("unknown")).toBe("light");
    });

    it("preserves explicit saved dark or system preference", () => {
      expect(normalizeThemePreference("dark")).toBe("dark");
      expect(normalizeThemePreference("system")).toBe("system");
      expect(normalizeThemePreference("light")).toBe("light");
    });

    it("resolves system preference based on OS media match", () => {
      expect(resolveThemePreference("system", true)).toBe("dark");
      expect(resolveThemePreference("system", false)).toBe("light");
      expect(resolveThemePreference("light", true)).toBe("light");
      expect(resolveThemePreference("dark", false)).toBe("dark");
    });
  });

  describe("Direction A Application Shell", () => {
    it("restores account-trigger focus when the account menu closes", () => {
      const setOpen = vi.fn();
      const focus = vi.fn();

      closeAccountMenu(setOpen, { focus });

      expect(setOpen).toHaveBeenCalledWith(false);
      expect(focus).toHaveBeenCalledOnce();
    });

    it("restores notification-trigger focus when the popover closes", () => {
      const setOpen = vi.fn();
      const focus = vi.fn();

      closeNotificationPopover(setOpen, { focus });

      expect(setOpen).toHaveBeenCalledWith(false);
      expect(focus).toHaveBeenCalledOnce();
    });

    it("renders the desktop wide sidebar with all 7 primary workspace and account links plus help", () => {
      const html = renderToStaticMarkup(
        createElement(LearnerShell, {
          current: "dashboard",
          userDisplayName: "Suyash R",
        }),
      );

      // Workspace links
      expect(html).toContain('href="/home"');
      expect(html).toContain("Dashboard");
      expect(html).toContain('href="/learning"');
      expect(html).toContain("My Learning");
      expect(html).toContain('href="/discover"');
      expect(html).toContain("Discover");
      expect(html).toContain('href="/progress"');
      expect(html).toContain("Progress");
      expect(html).toContain('href="/notifications"');
      expect(html).toContain("Notifications");

      // Account links
      expect(html).toContain('href="/profile"');
      expect(html).toContain("Profile");
      expect(html).toContain('href="/settings"');
      expect(html).toContain("Settings");
      expect(html).toContain(
        'href="mailto:admin@authorityclosers.com?subject=Authority%20Closers%20Learner%20Support"',
      );
      expect(html).toContain("Help");

      // User initials pill
      expect(html).toContain("SR");
      expect(html).toContain("Suyash R");
      expect(html).toContain("Learner");
    });

    it("renders the 5-item mobile bottom navigation bar with Home, Learning, Discover, Progress, More", () => {
      const html = renderToStaticMarkup(
        createElement(LearnerShell, { current: "learning" }),
      );

      expect(html).toContain('class="learner-bottom-nav"');
      expect(html).toContain('aria-label="Learner mobile navigation"');
      expect(html).toContain("Home");
      expect(html).toContain("Learning");
      expect(html).toContain("Discover");
      expect(html).toContain("Progress");
      expect(html).toContain("More");
    });

    it("marks the active route with aria-current page", () => {
      const dashboardHtml = renderToStaticMarkup(
        createElement(LearnerShell, { current: "dashboard" }),
      );
      expect(dashboardHtml).toContain('aria-current="page"');

      const discoverHtml = renderToStaticMarkup(
        createElement(LearnerShell, { current: "discover" }),
      );
      expect(discoverHtml).toContain('href="/discover"');
      expect(discoverHtml).toContain('aria-current="page"');
    });

    it("includes skip-to-content link for keyboard accessibility", () => {
      const html = renderToStaticMarkup(
        createElement(LearnerShell, { current: "home" }),
      );
      expect(html).toContain('class="skip-link"');
      expect(html).toContain('href="#main-content"');
      expect(html).toContain("Skip to content");
    });

    it("renders the search slot with shortcut badge and link to discover", () => {
      const html = renderToStaticMarkup(
        createElement(LearnerShell, { current: "dashboard" }),
      );
      expect(html).toContain('class="learner-header__search-trigger"');
      expect(html).toContain('href="/discover"');
      expect(html).toContain("Search for courses, lessons, and more");
      expect(html).toContain("⌘ K");
    });

    it("renders the notification action and profile button with accessibility attributes", () => {
      const html = renderToStaticMarkup(
        createElement(LearnerShell, {
          current: "dashboard",
          userDisplayName: "Alex Mercer",
        }),
      );
      expect(html).toContain('href="/notifications"');
      expect(html).toContain('aria-label="Notifications"');
      expect(html).toContain(
        'class="header-icon-button notification-bell-button"',
      );
      expect(html).toContain('aria-controls="learner-notifications-popover"');
      expect(html).toContain('aria-haspopup="dialog"');
      expect(html).toContain('class="learner-profile-button"');
      expect(html).toContain('aria-label="Account menu for Alex Mercer"');
      expect(html).toContain('aria-controls="learner-account-menu"');
      expect(html).toContain('aria-haspopup="menu"');
      expect(html).toContain("AM");
      expect(html).toContain("Alex Mercer");
    });

    it("renders one accessible rail control and tooltip titles on navigation links", () => {
      const html = renderToStaticMarkup(
        createElement(LearnerShell, { current: "dashboard" }),
      );
      const sidebarHtml = html.slice(
        html.indexOf('<aside id="learner-sidebar"'),
        html.indexOf("</aside>") + "</aside>".length,
      );
      const headerHtml = html.slice(
        html.indexOf('<header class="learner-header"'),
        html.indexOf("</header>") + "</header>".length,
      );
      expect(html).not.toContain('class="sidebar-collapse-btn"');
      expect(html).toContain('aria-expanded="true"');
      expect(html).toContain('title="Collapse sidebar"');
      expect(html).toContain('class="learner-sidebar-toggle"');
      expect(html.match(/class="learner-sidebar-toggle"/g)).toHaveLength(1);
      expect(html).toContain('aria-controls="learner-sidebar"');
      expect(sidebarHtml).toContain('class="learner-sidebar-toggle"');
      expect(headerHtml).not.toContain('class="learner-sidebar-toggle"');
      expect(html).toContain('class="learner-sidebar-wordmark__mark"');
      expect(html).toContain('class="learner-nav__label"');
      expect(html).toContain('title="Dashboard"');
      expect(html).toContain('title="My Learning"');
      expect(html).toContain('title="Discover"');
      expect(html).toContain('title="Progress"');
      expect(html).toContain('title="Notifications"');
      expect(html).toContain('title="Profile"');
      expect(html).toContain('title="Settings"');
      expect(html).toContain('title="Help"');
    });

    it("disables automatic prefetch for protected learner navigation", () => {
      const shellSource = readFileSync(
        new URL("../components/site-shell.tsx", import.meta.url),
        "utf8",
      );
      const learnerNavLink = shellSource.slice(
        shellSource.indexOf("function LearnerNavLink"),
        shellSource.indexOf("const SUPPORT_MAILTO"),
      );

      expect(learnerNavLink).toContain("prefetch={false}");
      expect(MobileLearnerBrand({}).props.prefetch).toBe(false);
      expect(shellSource).toContain(
        "href={ROUTES.discover}\n              prefetch={false}",
      );
      expect(shellSource).toContain(
        "href={ROUTES.settings}\n                      prefetch={false}",
      );
    });

    it("uses first and last initials for stable identity fallbacks", () => {
      expect(initialsForDisplayName("Suyash Rahegaonkar")).toBe("SR");
      expect(initialsForDisplayName("Dipak Vishwakarma Sharma")).toBe("DS");
      expect(initialsForDisplayName(" Learner ")).toBe("L");
      expect(initialsForDisplayName(" ")).toBe("AC");
    });

    it("keeps routine shell actions free of implementation-status toasts", () => {
      const shellSource = readFileSync(
        new URL("../components/site-shell.tsx", import.meta.url),
        "utf8",
      );
      expect(shellSource).not.toContain("Sidebar collapsed.");
      expect(shellSource).not.toContain("Sidebar expanded.");
      expect(shellSource).not.toContain("Help chat is ready;");
      expect(shellSource).not.toContain(
        "Notification history is not connected in this workspace yet.",
      );
      expect(shellSource).not.toContain("ac-toast");
      expect(shellSource).not.toContain("learner-toast");
      expect(shellSource).toContain("Help & Support");
      expect(shellSource).toContain("SUPPORT_MAILTO");
      expect(shellSource).not.toContain("learner-help-widget");
      expect(shellSource).not.toContain("live agent");
      expect(shellSource).not.toContain("connected LLM");
    });

    it("refreshes short-lived avatar delivery and falls back safely", () => {
      const shellSource = readFileSync(
        new URL("../components/site-shell.tsx", import.meta.url),
        "utf8",
      );
      expect(shellSource).toContain(
        "onError={() => setFailedAvatarUrl(imageUrl)}",
      );
      expect(shellSource).toContain("data-avatar-state={imageUrl ?");
      expect(shellSource).toContain("identity.email");
      expect(shellSource).toContain("account-menu-email");
      expect(shellSource).toContain("4 * 60 * 1000");
      expect(shellSource).toContain("avatarUpdateGenerationRef.current += 1");
      expect(shellSource).toContain(
        "updateGeneration === avatarUpdateGenerationRef.current",
      );
    });

    it("exports AppShell as the reusable canonical alias for LearnerShell", () => {
      expect(AppShell).toBe(LearnerShell);

      const html = renderToStaticMarkup(
        createElement(AppShell, {
          current: "dashboard",
          userDisplayName: "Elena Rostova",
        }),
      );
      expect(html).toContain("Elena Rostova");
      expect(html).toContain("ER");
      expect(html).toContain('aria-label="Learner workspace navigation"');
    });

    it("enforces Direction A navigation fidelity: 44px targets, active indicator bar, safe areas, and 320px polish", () => {
      const clarityCss = readFileSync(
        new URL("../learner-clarity.css", import.meta.url),
        "utf8",
      );
      // Skip link elevated above shell chrome with visible focus
      expect(clarityCss).toContain(".site-frame--learner .skip-link");
      expect(clarityCss).toContain("z-index: 100;");

      // Desktop rail 44px touch targets
      expect(clarityCss).toContain(
        ".site-frame--learner .learner-sidebar .learner-nav__link",
      );
      expect(clarityCss).toContain("min-height: 44px;");
      expect(clarityCss).toContain(
        ".site-frame--learner.site-frame--collapsed .learner-sidebar",
      );

      // Non-color status signal: visible indicator bar on mobile bottom nav active tab
      expect(clarityCss).toContain(
        ".site-frame--learner .learner-bottom-nav .learner-nav__link.is-current::before",
      );

      // Safe area padding on mobile bottom nav and drawer
      expect(clarityCss).toContain("env(safe-area-inset-bottom)");
      expect(clarityCss).toContain("env(safe-area-inset-top)");

      // Mobile keeps a visible 44px search trigger when the wide search slot hides.
      expect(clarityCss).toMatch(
        /\.site-frame--learner \.mobile-header-icon-button \{\s*display: inline-flex;\s*flex: 0 0 44px;/,
      );
      expect(clarityCss).not.toMatch(
        /\.site-frame--learner \.mobile-header-icon-button \{\s*display: none !important;/,
      );

      // 320px ultra-compact mobile polish
      expect(clarityCss).toContain("@media (max-width: 360px)");

      // Long copy truncation protection on user affordances
      expect(clarityCss).toContain(
        ".site-frame--learner .learner-profile__name",
      );
    });
  });

  describe("Bounded repair contracts", () => {
    it("keeps the mobile target, reduced-motion reset, copy, and long-copy guard explicit", () => {
      const shellSource = readFileSync(
        new URL("../components/site-shell.tsx", import.meta.url),
        "utf8",
      );
      const notificationSource = readFileSync(
        new URL("../components/notifications-runtime.tsx", import.meta.url),
        "utf8",
      );
      const dashboardSource = readFileSync(
        new URL("../components/dashboard-runtime.tsx", import.meta.url),
        "utf8",
      );
      const learningSource = readFileSync(
        new URL("../components/learning-runtime.tsx", import.meta.url),
        "utf8",
      );
      const learnerSource = readFileSync(
        new URL("../components/learner-runtime.tsx", import.meta.url),
        "utf8",
      );
      const discoverSource = readFileSync(
        new URL("../components/discover-runtime.tsx", import.meta.url),
        "utf8",
      );
      const progressSource = readFileSync(
        new URL("../components/progress-runtime.tsx", import.meta.url),
        "utf8",
      );
      const profileSource = readFileSync(
        new URL("../components/profile-runtime.tsx", import.meta.url),
        "utf8",
      );
      const clarityCss = readFileSync(
        new URL("../learner-clarity.css", import.meta.url),
        "utf8",
      );
      const shellSliceCss = readFileSync(
        new URL("../learner-next-slice.css", import.meta.url),
        "utf8",
      );
      const themeCss = readFileSync(
        new URL("../theme.css", import.meta.url),
        "utf8",
      );
      const courseSurfacesCss = readFileSync(
        new URL("../course-surfaces.css", import.meta.url),
        "utf8",
      );

      expect(shellSource).toContain("accountButtonRef.current");
      expect(shellSource).toContain('aria-controls="learner-account-menu"');
      expect(shellSource).toContain('role="menu"');
      expect(shellSource).toContain('role="menuitem"');
      expect(shellSource).toContain("notificationPopoverOpen");
      expect(shellSource).toContain("closeNotificationPopover");
      expect(notificationSource).toContain(
        'id="learner-notifications-popover"',
      );
      expect(shellSource).toContain("href={ROUTES.notifications}");
      expect(shellSource).not.toContain('userDisplayName = "Suyash"');
      expect(shellSource).not.toContain('className="header-badge-dot"');
      expect(shellSource).not.toContain("unreadCount");
      expect(shellSource).toContain("aria-expanded={!sidebarCollapsed}");
      expect(shellSource).toContain('className="learner-sidebar-toggle"');
      expect(shellSource).toContain('aria-controls="learner-sidebar"');
      expect(shellSource).toContain(
        '<span className="learner-nav__label">Help</span>',
      );
      expect(shellSource).toContain("SIDEBAR_COLLAPSE_STORAGE_KEY");
      expect(shellSource).toContain("window.localStorage.setItem(");
      expect(clarityCss).toContain(".learner-nav__label,");
      expect(clarityCss).not.toContain("span:not(.learner-nav__icon)");
      expect(clarityCss).not.toContain(".sidebar-collapse-btn");
      expect(clarityCss).not.toContain(".learner-sidebar__user-pill");
      expect(themeCss).not.toContain(".sidebar-collapse-btn");
      expect(courseSurfacesCss).toContain(
        "repeat(auto-fit, minmax(min(100%, 300px), 1fr))",
      );
      expect(courseSurfacesCss).toMatch(
        /\.ac-program-grid\s*>\s*\.ac-program-card:only-child\s*\{[\s\S]*?width:\s*min\(100%,\s*380px\);[\s\S]*?justify-self:\s*start;/,
      );
      expect(shellSource).not.toContain("setHelpOpen");
      expect(shellSource).not.toContain("Open help chatbox");
      expect(shellSource).toContain(
        'if (event.key === "Tab") {\n      // Let the browser continue through the document\'s tab order.',
      );
      expect(shellSource).not.toContain(
        'if (event.key === "Tab") {\n      event.preventDefault();\n      closeAccountMenu',
      );
      expect(shellSource).toContain("handlePointerDown");
      expect(shellSource).toContain(
        "!accountButtonRef.current?.contains(target)",
      );
      expect(clarityCss).toContain(".mobile-only");
      expect(clarityCss).toContain(".desktop-only");
      expect(clarityCss).toMatch(
        /\.header-icon-button\s*\{[\s\S]*?width:\s*44px;[\s\S]*?height:\s*44px;/,
      );
      expect(clarityCss).toContain(
        "grid-template-columns: repeat(5, minmax(0, 1fr));",
      );
      expect(clarityCss).toContain(
        ".site-frame--learner .continue-learning-hero__actions",
      );
      expect(clarityCss).toContain("animation: none !important;");
      expect(clarityCss).toContain("transition: none !important;");
      expect(clarityCss).toContain(
        ".site-frame--learner .practice-step-card:hover",
      );
      expect(learningSource).toContain("api.learningCollection");
      expect(learningSource).toContain("savedFilterAvailable");
      expect(learningSource).not.toContain(
        "Module content will be released in the next sequence.",
      );
      expect(discoverSource).toContain(
        "Published programs in the Authority Closers catalog.",
      );
      expect(discoverSource).not.toContain(
        "available to this learner workspace",
      );
      expect(progressSource).toContain("state.error.status === 403");
      expect(progressSource).toContain("Progress access is unavailable");
      expect(dashboardSource).toContain("draftCleanup");
      expect(learningSource).toContain("draftCleanup");
      expect(discoverSource).toContain("draftCleanup");
      expect(profileSource).toContain("draftCleanup");
      expect(progressSource).toContain("draftCleanup");
      expect(dashboardSource).toContain("const offlineRead = data.offlineRead");
      expect(learnerSource).toContain(
        "export function useInvalidateDraftsWithoutMembership",
      );
      expect(learnerSource).toContain("Approved lesson media is unavailable");
      expect(clarityCss).toContain(".discover-view .alert-box");
      expect(clarityCss).toContain(".activity-media-state {");
      expect(clarityCss).toContain("max-width: min(28vw, 180px);");
      expect(clarityCss).toContain("text-overflow: ellipsis;");
      expect(clarityCss).toContain("overflow-wrap: anywhere;");
      expect(clarityCss).toContain(
        ".site-frame--learner .notification-popover",
      );
      expect(clarityCss).toContain(
        ".site-frame--learner .notification-popover__action-link",
      );
      expect(shellSliceCss).toContain("--ac-mark-cut: var(--theme-action);");
      expect(shellSliceCss).toContain("@media (max-width: 1023px)");
      expect(shellSliceCss).toMatch(
        /@media \(max-width: 1023px\)[\s\S]*?\.site-frame--learner \.learner-help-widget \{[\s\S]*?display: none;/,
      );
      expect(clarityCss).toContain(
        ".site-frame--learner .progress-summary__number::after",
      );
      expect(clarityCss).toContain("--progress-percentage");
      expect(clarityCss).toContain("@media (max-width: 360px)");
      expect(clarityCss).toContain(".section-header-row");
      expect(dashboardSource).toContain("Today&apos;s plan");
      expect(dashboardSource).toContain("Your course progress");
      expect(dashboardSource).not.toContain("Your weekly activity");
      expect(dashboardSource).toContain("calendarStatus");
      expect(dashboardSource).toContain("planItems");
      expect(dashboardSource).toContain("ROUTES.calendar");
      expect(dashboardSource).toContain("learning.projection.completed_count");
      expect(dashboardSource).not.toContain("DEV_MOCK_DATA");
      expect(dashboardSource).not.toContain("Today at 9:41 AM");
      expect(dashboardSource).not.toContain("Coach Alex");
      expect(dashboardSource).not.toContain("Launching June 2, 2025");
    });
  });

  describe("Route-shaped skeletons", () => {
    it("renders DashboardSkeleton with live status and single sr-only h1", () => {
      const html = renderToStaticMarkup(createElement(DashboardSkeleton));
      expect(html).toContain('class="dashboard-skeleton"');
      expect(html).toContain('role="status"');
      expect(html).toContain('aria-busy="true"');
      expect(html).toContain("<h1");
      expect(html).toContain("Learning Command Center");
    });

    it("renders LearningSkeleton with single sr-only h1", () => {
      const html = renderToStaticMarkup(createElement(LearningSkeleton));
      expect(html).toContain('class="learning-skeleton"');
      expect(html).toContain("<h1");
      expect(html).toContain("My Learning");
    });

    it("renders DiscoverSkeleton with single sr-only h1", () => {
      const html = renderToStaticMarkup(createElement(DiscoverSkeleton));
      expect(html).toContain('class="discover-skeleton"');
      expect(html).toContain("<h1");
      expect(html).toContain("Discover Programs");
    });

    it("renders ProfileSkeleton with single sr-only h1", () => {
      const html = renderToStaticMarkup(createElement(ProfileSkeleton));
      expect(html).toContain('class="profile-skeleton"');
      expect(html).toContain("<h1");
      expect(html).toContain("Learner Profile");
    });

    it("renders NotificationsSkeleton with single sr-only h1", () => {
      const html = renderToStaticMarkup(createElement(NotificationsSkeleton));
      expect(html).toContain('class="notifications-skeleton"');
      expect(html).toContain("<h1");
      expect(html).toContain("Notifications");
    });

    it("renders ProgressSkeleton with single sr-only h1", () => {
      const html = renderToStaticMarkup(createElement(ProgressSkeleton));
      expect(html).toContain('class="progress-skeleton"');
      expect(html).toContain("<h1");
      expect(html).toContain("Learning Progress");
    });

    it("renders SettingsSkeleton with a route-shaped two-card ledger", () => {
      const html = renderToStaticMarkup(createElement(SettingsSkeleton));
      expect(html).toContain('class="settings-route-skeleton"');
      expect(html).toContain("settings-route-skeleton__grid");
      expect(html).toContain("<h1");
      expect(html).toContain("Account Settings");
    });

    it.each([
      ["dashboard", DashboardPage, "dashboard-skeleton"],
      ["learning", LearningPage, "learning-skeleton"],
      ["discover", DiscoverPage, "discover-skeleton"],
      ["notifications", NotificationsPage, "notifications-skeleton"],
      ["profile", ProfilePage, "profile-skeleton"],
      ["progress", ProgressPage, "progress-skeleton"],
      ["settings", SettingsPage, "settings-route-skeleton"],
    ])(
      "uses the %s skeleton for the simulated loading route",
      async (_name, page, className) => {
        const element = await page({
          searchParams: Promise.resolve({ state: "LOADING" }),
        });
        const html = renderToStaticMarkup(element);

        expect(html).toContain(`class="${className}`);
        expect(html).not.toContain("Getting the next useful thing ready");
      },
    );
  });

  describe("In-flight GET request deduplication", () => {
    it("deduplicates simultaneous in-flight GET requests to the same endpoint", async () => {
      let fetchCount = 0;
      let resolveFetch!: (res: Response) => void;
      const deferred = new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      });

      const customFetcher = vi.fn(async () => {
        fetchCount++;
        return deferred;
      });

      const api = createLearnerApi(customFetcher as unknown as typeof fetch);

      // Launch two concurrent GET requests to /v1/me
      const call1 = api.me();
      const call2 = api.me();

      expect(fetchCount).toBe(1);

      resolveFetch(
        new Response(
          JSON.stringify({
            person_id: "p1",
            email: "learner@example.com",
            display_name: "Learner",
            email_verified_at: "2026-09-01T00:00:00Z",
            selected_tenant_id: null,
            membership_role: "learner",
            permissions: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

      const [res1, res2] = await Promise.all([call1, call2]);
      expect(res1.person_id).toBe("p1");
      expect(res2.person_id).toBe("p1");
      expect(fetchCount).toBe(1);
    });

    it("does not share GET requests with different headers or caller signals", async () => {
      const fetcher = vi.fn(
        async (input: RequestInfo | URL, init?: RequestInit) => {
          void input;
          void init;
          return new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        },
      );
      const api = createLearnerApi(fetcher as unknown as typeof fetch);

      await Promise.all([
        api.request("/v1/me", { headers: { "X-Context": "one" } }),
        api.request("/v1/me", { headers: { "X-Context": "two" } }),
      ]);
      const firstSignal = new AbortController().signal;
      const secondSignal = new AbortController().signal;
      await Promise.all([
        api.request("/v1/context", { signal: firstSignal }),
        api.request("/v1/context", { signal: secondSignal }),
      ]);

      expect(fetcher).toHaveBeenCalledTimes(4);
      expect(fetcher.mock.calls[2][1]?.signal).toBe(firstSignal);
      expect(fetcher.mock.calls[3][1]?.signal).toBe(secondSignal);
    });
  });

  describe("Server-backed first-slice data and failure semantics", () => {
    it("selects only state-and-action-authorized next activity", () => {
      expect(firstActionableActivity(learning)?.id).toBe("available");
      expect(isActivityActionable(learning.modules[0].activities[1])).toBe(
        false,
      );
      expect(isActivityActionable(learning.modules[0].activities[2])).toBe(
        true,
      );
    });

    it("honors the server-owned next activity when it is still action-enabled", () => {
      const available = learning.modules[0].activities[2];
      const later = {
        ...available,
        id: "later",
        position: 4,
        explanation: { ...available.explanation, activity_id: "later" },
      };
      const guided = {
        ...learning,
        modules: [
          {
            ...learning.modules[0],
            activities: [...learning.modules[0].activities, later],
          },
        ],
        projection: { ...learning.projection, next_activity_id: "later" },
      } satisfies LearningResponse;

      expect(firstActionableActivity(guided)?.id).toBe("later");
    });

    it("falls back safely when the server pointer is stale or not actionable", () => {
      const guided = {
        ...learning,
        projection: { ...learning.projection, next_activity_id: "awaiting" },
      } satisfies LearningResponse;

      expect(firstActionableActivity(guided)?.id).toBe("available");
    });

    it("honors an explicit server no-action result", () => {
      const optional = {
        ...learning.modules[0].activities[2],
        id: "optional",
        required: false,
        state: "in_progress",
      };
      const noAction = {
        ...learning,
        modules: [
          {
            ...learning.modules[0],
            activities: [
              ...learning.modules[0].activities.map((activity) => ({
                ...activity,
                state: "completed",
                allowed_actions: [],
              })),
              optional,
            ],
          },
        ],
        projection: { ...learning.projection, next_activity_id: null },
      } satisfies LearningResponse;

      expect(firstActionableActivity(noAction)).toBeUndefined();
    });

    it("normalizes authored module separators only for presentation", () => {
      expect(presentationModuleTitle("Opening — Module 1")).toBe(
        "Opening · Module 1",
      );
      expect(presentationModuleTitle("Opening — Module 1")).not.toBe(
        "Opening — Module 1",
      );
    });

    it("loads Today’s plan only from the tenant-scoped explicit plan projection", async () => {
      const tenantMe = { ...me, selected_tenant_id: "tenant-1" };
      const api = apiFor({
        me: vi.fn(async () => tenantMe),
        calendar: vi.fn(async () => calendar),
      });

      const result = await loadDashboardData(api);

      expect(result).toMatchObject({
        kind: "ready",
        data: {
          calendar,
          calendarStatus: "available",
        },
      });
      expect(api.calendar).toHaveBeenCalledWith({ signal: undefined });
    });

    it("keeps the dashboard ready when the optional plan projection is unavailable", async () => {
      const tenantMe = { ...me, selected_tenant_id: "tenant-1" };
      const api = apiFor({
        me: vi.fn(async () => tenantMe),
        calendar: vi.fn(async () => {
          throw new ApiError(503, "plan service unavailable");
        }),
      });

      const result = await loadDashboardData(api);

      expect(result).toMatchObject({
        kind: "ready",
        data: { calendarStatus: "unavailable" },
      });
    });

    it("loads the complete learner collection instead of selecting a free course", async () => {
      const api = apiFor();

      const result = await loadLearningData(api);

      expect(result.courses).toHaveLength(1);
      expect(result.courses[0].program_slug).toBe(freeCourse.slug);
      expect(result.savedFilterAvailable).toBe(false);
      expect(api.learningCollection).toHaveBeenCalledWith(50, {
        signal: undefined,
      });
      expect(api.listPrograms).not.toHaveBeenCalled();
    });

    it("disables activity navigation when the learning projection is an offline copy", () => {
      const offlineLearning = JSON.parse(
        JSON.stringify(learning),
      ) as LearningResponse;
      markOfflineRead(offlineLearning, 7_000);
      const html = renderToStaticMarkup(
        createElement(LearningActivityNavigation, {
          activity: offlineLearning.modules[0].activities[2],
        }),
      );

      expect(html).toContain("Reconnect to open");
      expect(html).toContain('aria-disabled="true"');
      expect(html).not.toContain('href="/activity/available"');
    });

    it("preserves the onboarding gate before dashboard reads", async () => {
      const api = apiFor({
        onboarding: vi.fn(async () => ({
          person_id: me.person_id,
          experience_context: null,
          learning_goal: null,
          practice_situation: null,
          weekly_minutes: null,
          status: "in_progress" as const,
          current_step: 1,
          revision: 1,
          updated_at: "2026-09-01T00:00:00Z",
          next_action_href: "/onboarding",
          next_action_reason: "finish setup",
        })),
      });
      const result = await loadDashboardData(api);
      expect(result.kind).toBe("onboarding");
      expect(api.listPrograms).not.toHaveBeenCalled();
    });

    it("only treats a confirmed learning 404 as no enrollment", async () => {
      const notEnrolled = apiFor({
        learning: vi.fn(async () => {
          throw new ApiError(404, "not enrolled");
        }),
      });
      const result = await loadDashboardData(notEnrolled);
      expect(result.kind).toBe("ready");

      const forbidden = apiFor({
        learning: vi.fn(async () => {
          throw new ApiError(403, "forbidden");
        }),
      });
      await expect(loadDashboardData(forbidden)).rejects.toMatchObject({
        status: 403,
      });

      const serviceFailure = apiFor({
        learningCollection: vi.fn(async () => {
          throw new ApiError(500, "service failure");
        }),
      });
      await expect(loadLearningData(serviceFailure)).rejects.toMatchObject({
        status: 500,
      });

      const discoverNotEnrolled = apiFor({
        learning: vi.fn(async () => {
          throw new ApiError(404, "not enrolled");
        }),
      });
      expect((await loadDiscoverData(discoverNotEnrolled)).learning).toBeNull();

      const discoverFailure = apiFor({
        learning: vi.fn(async () => {
          throw new ApiError(500, "service failure");
        }),
      });
      await expect(loadDiscoverData(discoverFailure)).rejects.toMatchObject({
        status: 500,
      });
    });

    it("publishes Discover identity before a later catalog failure", async () => {
      const identityWithoutMembership: MeResponse = {
        ...me,
        membership_role: null,
      };
      const onIdentity = vi.fn();
      const api = apiFor({
        me: vi.fn(async () => identityWithoutMembership),
        listPrograms: vi.fn(async () => {
          throw new ApiError(503, "catalog unavailable");
        }),
      });

      await expect(
        loadDiscoverData(api, undefined, false, onIdentity),
      ).rejects.toMatchObject({ status: 503 });
      expect(onIdentity).toHaveBeenCalledOnce();
      expect(onIdentity).toHaveBeenCalledWith(identityWithoutMembership);
    });

    it("loads only anonymous published catalog data in the localhost staging preview", async () => {
      const previewApi = apiFor({ me: vi.fn() });
      const result = await loadDiscoverData(previewApi, undefined, true);

      expect(result.publicCatalogPreview).toBe(true);
      expect(result.programs).toHaveLength(1);
      expect(result.learning).toBeNull();
      expect(previewApi.me).not.toHaveBeenCalled();
      expect(previewApi.learning).not.toHaveBeenCalled();
    });

    it("threads caller cancellation through every progress read", async () => {
      const controller = new AbortController();
      const api = apiFor();

      await expect(
        loadProgressData(api, controller.signal),
      ).resolves.toMatchObject({
        status: "ready",
        learning,
      });

      expect(api.me).toHaveBeenCalledWith({ signal: controller.signal });
      expect(api.listPrograms).toHaveBeenCalledWith(50, {
        signal: controller.signal,
      });
      expect(api.learning).toHaveBeenCalledWith("program-1", undefined, {
        signal: controller.signal,
      });
    });

    it("aborts settings reads when their load generation is stopped", () => {
      let meSignal: AbortSignal | undefined;
      const api = apiFor({
        me: vi.fn((options) => {
          meSignal = options.signal;
          return new Promise<MeResponse>(() => undefined);
        }),
      });

      const stop = startSettingsResourceLoad(api, () => undefined);
      expect(meSignal?.aborted).toBe(false);
      stop();
      expect(meSignal?.aborted).toBe(true);
    });

    it("loads profile identity before onboarding and retains partial errors", async () => {
      const order: string[] = [];
      const api = apiFor({
        me: vi.fn(async () => {
          order.push("me");
          return me;
        }),
        onboarding: vi.fn(async () => {
          order.push("onboarding");
          throw new ApiError(503, "unavailable");
        }),
      });
      const result = await loadProfileData(api);
      expect(order).toEqual(["me", "onboarding"]);
      expect(result.me).toBe(me);
      expect(result.onboarding).toBeNull();
      expect(result.onboardingError).toMatchObject({ status: 503 });

      const unauthorized = apiFor({
        me: vi.fn(async () => {
          throw new ApiError(401, "expired");
        }),
        onboarding: vi.fn(),
      });
      await expect(loadProfileData(unauthorized)).rejects.toMatchObject({
        status: 401,
      });
      expect(unauthorized.onboarding).not.toHaveBeenCalled();
    });

    it("keeps identity and preferences available when avatar delivery is gated", async () => {
      const api = apiFor({
        profileAvatar: vi.fn(async () => {
          throw new ApiError(503, "media storage is unavailable");
        }),
      });

      const result = await loadProfileData(api);
      expect(result.me).toBe(me);
      expect(result.onboarding).not.toBeNull();
      expect(result.avatar).toBeNull();
      expect(result.avatarError).toMatchObject({ status: 503 });
    });

    it("does not fabricate catalog or notification content", () => {
      const discoverHtml = renderToStaticMarkup(
        createElement(DiscoverRuntime, { api: apiFor() }),
      );
      const notificationsHtml = renderToStaticMarkup(
        createElement(NotificationsRuntime),
      );
      const shellHtml = renderToStaticMarkup(
        createElement(LearnerShell, { current: "profile" }),
      );
      const signOutHtml = renderToStaticMarkup(createElement(SignOutControl));

      expect(discoverHtml).not.toContain("Advanced Objection Mastery");
      expect(discoverHtml).not.toContain("Enterprise Closing Architecture");
      expect(notificationsHtml).not.toContain("Welcome to Authority Closers");
      expect(notificationsHtml).not.toContain("Mark all read");
      expect(shellHtml).toContain('aria-current="page"');
      expect(shellHtml).toContain('aria-controls="learner-more-drawer"');
      expect(shellHtml).not.toContain("/settings#session");
      expect(signOutHtml).toContain("Sign out");
      expect(signOutHtml).toContain("sign-out-control");
    });
  });

  describe("Route separation invariants", () => {
    it("keeps distinct endpoints for all major learner destinations", () => {
      expect(ROUTES.dashboard).toBe("/home");
      expect(ROUTES.learning).toBe("/learning");
      expect(ROUTES.discover).toBe("/discover");
      expect(ROUTES.progress).toBe("/progress");
      expect(ROUTES.notifications).toBe("/notifications");
      expect(ROUTES.profile).toBe("/profile");
      expect(ROUTES.settings).toBe("/settings");

      // Verify no collision between learning journey and home dashboard
      expect(ROUTES.dashboard).not.toBe(ROUTES.learning);
    });

    it("encodes every dynamic route segment", () => {
      expect(ROUTES.programDetail("course/one")).toBe("/programs/course%2Fone");
      expect(ROUTES.programLearning("course one")).toBe("/learn/course%20one");
      expect(ROUTES.module("course/one", "module?one")).toBe(
        "/learn/course%2Fone/module/module%3Fone",
      );
      expect(ROUTES.activity("activity#one")).toBe("/activity/activity%23one");
      expect(ROUTES.completion("course/one")).toBe(
        "/learn/course%2Fone/complete",
      );
      expect(ROUTES.certificate("certificate/one")).toBe(
        "/certificates/certificate%2Fone",
      );
    });
  });
});
