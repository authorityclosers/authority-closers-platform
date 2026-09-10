import { readFileSync } from "node:fs";
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import ActivityPage from "../activity/[activityId]/page";
import CallbackPage from "../auth/callback/page";
import CertificatePage from "../certificates/[certificateId]/page";
import { ActivityRenderer } from "../components/activity-renderers";
import {
  ConnectedActivityWorkspace,
  activityStateForScope,
  createActivityOperationLock,
  enrollmentFailureMessage,
  FREE_COURSE_SLUG,
  identityState,
  isFreeEnrollmentProgram,
  learnerHomeMode,
  LearningActivityNavigation,
  LearningModules,
  LearnerHomeEnrollmentCard,
  learningPathContinueTarget,
  learningPathMatchesActivity,
  loadActivityEntryState,
  refreshActivityLearningSnapshots,
  selectPublishedFreeCourse,
} from "../components/learner-runtime";
import {
  hasMembershipRole,
  MembershipDraftCleanupNotice,
  MembershipUnavailable,
} from "../components/membership-availability";
import {
  SignOutFailure,
  signOutFailureMessage,
} from "../components/sign-out-control";
import { LoginForm, routeAfterOnboarding } from "../components/login-form";
import {
  ONBOARDING_USE_LOCAL_COPY_LABEL,
  OnboardingCompletionState,
  OnboardingForm,
  createOnboardingMutationLock,
  onboardingEditorStateFromLocalRecovery,
  onboardingLocalDraftNeedsEditing,
  reconcileOnboardingLocalCleanup,
  type OnboardingFormProps,
} from "../components/onboarding-form";
import { ThemeControl } from "../components/theme-control";
import { ActivityStatusPill, ProgressMeter } from "../components/shared-ui";
import { Breadcrumbs, LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import LearnerHomePage from "../home/page";
import LearningPage from "../learning/page";
import DiscoverPage from "../discover/page";
import ProfilePage from "../profile/page";
import NotificationsPage from "../notifications/page";
import ProgramLearningPage from "../learn/[programSlug]/page";
import CompletionPage from "../learn/[programSlug]/complete/page";

import ModulePage from "../learn/[programSlug]/module/[moduleId]/page";
import LoginPage from "../login/page";
import ForgotPasswordPage from "../forgot-password/page";
import manifest from "../manifest";
import OfflinePage from "../offline/page";
import { AuthFlowPage, authFlowStepState } from "../components/auth-flow-page";
import OnboardingPage from "../onboarding/page";
import {
  onboardingHref,
  onboardingReturnHref,
  parseOnboardingReturnIntent,
} from "./onboarding-route";
import ProgressPage from "../progress/page";
import PublicHomePage from "../page";
import PrivacyPage from "../privacy/page";
import ProgramDetailPage from "../programs/[slug]/page";
import RegisterPage from "../register/page";
import ResetPasswordPage from "../reset-password/page";
import SettingsPage from "../settings/page";
import SessionExpiredPage from "../session-expired/page";
import TermsPage from "../terms/page";
import VerifyEmailPage from "../verify-email/page";
import {
  freeCourse,
  getActivityById,
  getActivityLocationById,
  isActivityPayloadAllowed,
  isModulePayloadAllowed,
} from "./course-data";
import { ROUTES } from "./routes";
import {
  isContentVisible,
  isSurfaceStateSimulationEnabled,
  parseSurfaceState,
  stateQuery,
  SURFACE_STATE_ORDER,
  type SurfaceState,
} from "./surface-state";
import {
  ApiError,
  type ActivityResponse,
  type LearnerApi,
  type LearningResponse,
  type MeResponse,
  type OnboardingResponse,
} from "./learner-api";
import {
  onboardingServerFingerprint,
  peekOnboardingLocalDraftForCleanup,
  writeOnboardingLocalDraft,
  type OnboardingRecoveryLockManager,
} from "./local-drafts";
import { markOfflineRead } from "./offline-read-cache";

function h1Count(html: string): number {
  return html.match(/<h1(?:\s|>)/g)?.length ?? 0;
}

function queryValue(state: SurfaceState): string | undefined {
  return state === "DEFAULT"
    ? undefined
    : state.toLowerCase().replaceAll("_", "-");
}

function onboardingProfile(
  overrides: Partial<OnboardingResponse> = {},
): OnboardingResponse {
  return {
    person_id: "person-test",
    experience_context: "sales",
    learning_goal: null,
    practice_situation: null,
    weekly_minutes: null,
    status: "in_progress",
    current_step: 2,
    revision: 4,
    updated_at: "2026-09-02T00:00:00Z",
    next_action_href: "/onboarding",
    next_action_reason: "complete learning setup",
    ...overrides,
  };
}

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => void values.delete(key),
    setItem: (key, value) => void values.set(key, value),
  };
}

function exclusiveLockManager(): OnboardingRecoveryLockManager {
  let held = false;
  return {
    request: async (_name, _options, callback) => {
      if (held) return callback(null);
      held = true;
      try {
        return await callback({});
      } finally {
        held = false;
      }
    },
  };
}

const routeRenderers: Array<[string, (state?: string) => Promise<ReactNode>]> =
  [
    [
      "public home",
      (state) => PublicHomePage({ searchParams: Promise.resolve({ state }) }),
    ],
    [
      "program detail",
      (state) =>
        ProgramDetailPage({
          params: Promise.resolve({ slug: "free-course" }),
          searchParams: Promise.resolve({ state }),
        }),
    ],
    [
      "login",
      (state) => LoginPage({ searchParams: Promise.resolve({ state }) }),
    ],
    ["register", async () => RegisterPage()],
    ["forgot password", async () => ForgotPasswordPage()],
    ["verify email", async () => VerifyEmailPage()],
    ["reset password", async () => ResetPasswordPage()],
    ["session expired", async () => SessionExpiredPage()],
    ["offline fallback", async () => OfflinePage()],
    [
      "callback",
      (state) => CallbackPage({ searchParams: Promise.resolve({ state }) }),
    ],
    [
      "onboarding",
      (state) => OnboardingPage({ searchParams: Promise.resolve({ state }) }),
    ],
    [
      "learner home",
      (state) => LearnerHomePage({ searchParams: Promise.resolve({ state }) }),
    ],
    [
      "learning",
      (state) => LearningPage({ searchParams: Promise.resolve({ state }) }),
    ],
    [
      "discover",
      (state) => DiscoverPage({ searchParams: Promise.resolve({ state }) }),
    ],
    [
      "profile",
      (state) => ProfilePage({ searchParams: Promise.resolve({ state }) }),
    ],
    [
      "notifications",
      (state) =>
        NotificationsPage({ searchParams: Promise.resolve({ state }) }),
    ],
    [
      "progress",
      (state) => ProgressPage({ searchParams: Promise.resolve({ state }) }),
    ],
    [
      "settings",
      (state) => SettingsPage({ searchParams: Promise.resolve({ state }) }),
    ],

    [
      "program learning",
      (state) =>
        ProgramLearningPage({
          params: Promise.resolve({ programSlug: "free-course" }),
          searchParams: Promise.resolve({ state }),
        }),
    ],
    [
      "module",
      (state) =>
        ModulePage({
          params: Promise.resolve({
            programSlug: "free-course",
            moduleId: "module-01",
          }),
          searchParams: Promise.resolve({ state }),
        }),
    ],
    [
      "activity",
      (state) =>
        ActivityPage({
          params: Promise.resolve({ activityId: "reflect" }),
          searchParams: Promise.resolve({ state }),
        }),
    ],
    [
      "completion",
      (state) =>
        CompletionPage({
          params: Promise.resolve({ programSlug: "free-course" }),
          searchParams: Promise.resolve({ state }),
        }),
    ],
    [
      "certificate",
      (state) =>
        CertificatePage({
          params: Promise.resolve({ certificateId: "preview-certificate" }),
          searchParams: Promise.resolve({ state }),
        }),
    ],
  ];

describe("learner route and state primitives", () => {
  it("keeps the universal state order explicit and deterministic", () => {
    expect(SURFACE_STATE_ORDER).toEqual([
      "DEFAULT",
      "LOADING",
      "EMPTY",
      "ERROR_RETRYABLE",
      "ERROR_TERMINAL",
      "OFFLINE",
      "PERMISSION_DENIED",
      "LOCKED",
      "PARTIAL",
      "SUCCESS_FEEDBACK",
    ]);
  });

  it("normalizes query state without allowing unsupported values", () => {
    expect(parseSurfaceState("offline")).toBe("OFFLINE");
    expect(parseSurfaceState("error-retryable")).toBe("ERROR_RETRYABLE");
    expect(parseSurfaceState(["partial", "locked"])).toBe("PARTIAL");
    expect(parseSurfaceState("not-a-state")).toBe("DEFAULT");
    expect(parseSurfaceState(undefined)).toBe("DEFAULT");
  });

  it("disables query-string state simulation in production", () => {
    expect(isSurfaceStateSimulationEnabled("production")).toBe(false);
    expect(isSurfaceStateSimulationEnabled("development")).toBe(true);
    expect(parseSurfaceState("success-feedback", "production")).toBe("DEFAULT");
    expect(parseSurfaceState("permission-denied", "production")).toBe(
      "DEFAULT",
    );
    expect(parseSurfaceState("success-feedback", "development")).toBe(
      "SUCCESS_FEEDBACK",
    );
  });

  it("only renders resource content for usable states", () => {
    expect(isContentVisible("DEFAULT")).toBe(true);
    expect(isContentVisible("PARTIAL")).toBe(true);
    expect(isContentVisible("SUCCESS_FEEDBACK")).toBe(true);
    expect(isContentVisible("LOADING")).toBe(false);
    expect(isContentVisible("PERMISSION_DENIED")).toBe(false);
  });

  it("builds the preview state retry link without changing the route", () => {
    expect(stateQuery(ROUTES.activity("reflect"), "DEFAULT")).toBe(
      "/activity/reflect?state=default",
    );
    expect(stateQuery("/learn/free-course?tab=path", "OFFLINE")).toBe(
      "/learn/free-course?tab=path&state=offline",
    );
  });

  it("keeps the canonical learner journey route shapes stable", () => {
    expect(ROUTES.privacy).toBe("/privacy");
    expect(ROUTES.terms).toBe("/terms");
    expect(ROUTES.register).toBe("/register");
    expect(ROUTES.forgotPassword).toBe("/forgot-password");
    expect(ROUTES.verifyEmail).toBe("/verify-email");
    expect(ROUTES.resetPassword).toBe("/reset-password");
    expect(ROUTES.sessionExpired).toBe("/session-expired");
    expect(ROUTES.onboarding).toBe("/onboarding");
    expect(ROUTES.learnerHome).toBe("/home");
    expect(ROUTES.dashboard).toBe("/home");
    expect(ROUTES.learning).toBe("/learning");
    expect(ROUTES.myLearning).toBe("/learning");
    expect(ROUTES.discover).toBe("/discover");
    expect(ROUTES.notifications).toBe("/notifications");
    expect(ROUTES.profile).toBe("/profile");
    expect(ROUTES.practice).toBe("/home#practice");
    expect(ROUTES.progress).toBe("/progress");
    expect(ROUTES.settings).toBe("/settings");

    expect(ROUTES.programDetail("free-course")).toBe("/programs/free-course");
    expect(ROUTES.programLearning("free-course")).toBe("/learn/free-course");
    expect(ROUTES.module("free-course", "module-01")).toBe(
      "/learn/free-course/module/module-01",
    );
    expect(ROUTES.activity("improve")).toBe("/activity/improve");
    expect(ROUTES.completion("free-course")).toBe(
      "/learn/free-course/complete",
    );
    expect(ROUTES.certificate("preview-certificate")).toBe(
      "/certificates/preview-certificate",
    );
  });
});

describe("installable browser shell", () => {
  it("publishes a standalone learner manifest without native-app claims", () => {
    const metadata = manifest();

    expect(metadata.display).toBe("standalone");
    expect(metadata.start_url).toBe("/");
    expect(metadata.scope).toBe("/");
    expect(metadata.name).toBe("Closers Academy · Cohorva");
    expect(metadata.icons).toEqual([
      expect.objectContaining({
        src: "/brand/closers-academy-v0.1/icon-192.png",
        sizes: "192x192",
        purpose: "any",
      }),
      expect.objectContaining({
        src: "/brand/closers-academy-v0.1/icon-512.png",
        sizes: "512x512",
        purpose: "maskable",
      }),
    ]);
  });

  it("keeps the offline fallback honest about canonical progress", () => {
    const html = renderToStaticMarkup(createElement(OfflinePage));

    expect(h1Count(html)).toBe(1);
    expect(html).toContain("You are offline");
    expect(html).toContain(
      "No local response is treated as canonical progress",
    );
  });
});

describe("staging consent support pages", () => {
  it("publishes honest privacy and terms boundaries without production claims", () => {
    const privacy = renderToStaticMarkup(createElement(PrivacyPage));
    const terms = renderToStaticMarkup(createElement(TermsPage));

    expect(h1Count(privacy)).toBe(1);
    expect(h1Count(terms)).toBe(1);
    expect(privacy).toContain("Staging test document");
    expect(privacy).toContain("does not receive your Google password");
    expect(terms).toContain("Not final production legal terms");
    expect(terms).toContain("No purchase");
    expect(privacy).toContain("admin@authorityclosers.com");
    expect(terms).toContain("admin@authorityclosers.com");
  });
});

describe("canonical progression access", () => {
  it("uses preview-only activity status when no durable evidence exists", () => {
    const firstModule = freeCourse.modules[0];
    const status = renderToStaticMarkup(
      createElement(ActivityStatusPill, {
        status: getActivityById("watch")?.status ?? "LOCKED",
      }),
    );

    expect(firstModule?.activities.map((activity) => activity.status)).toEqual([
      "PREVIEW",
      "PREVIEW",
      "PREVIEW",
    ]);
    expect(status).toContain("Preview only");
    expect(status).not.toContain("Complete");
  });

  it("keeps every child of the locked module canonically locked", () => {
    const lockedModule = freeCourse.modules.find(
      (courseModule) => courseModule.status === "LOCKED",
    );

    expect(lockedModule).toBeDefined();
    expect(isModulePayloadAllowed(lockedModule)).toBe(false);
    expect(
      lockedModule?.activities.every(
        (activity) => activity.status === "LOCKED",
      ),
    ).toBe(true);
    expect(isActivityPayloadAllowed(getActivityLocationById("review"))).toBe(
      false,
    );
    expect(isActivityPayloadAllowed(getActivityLocationById("improve"))).toBe(
      false,
    );
    expect(isActivityPayloadAllowed(getActivityLocationById("reflect"))).toBe(
      true,
    );
  });

  it.each(["review", "improve"])(
    "does not substitute local preview data for direct activity URL %s",
    async (activityId) => {
      const page = await ActivityPage({
        params: Promise.resolve({ activityId }),
        searchParams: Promise.resolve({}),
      });
      const html = renderToStaticMarkup(page);

      expect(html).toContain("Activity");
      expect(html).toContain("Preparing your workspace");
      expect(html).toContain('aria-busy="true"');
      expect(html).not.toContain('data-state="LOCKED"');
      expect(html).not.toContain("Complete the previous step first");
      expect(html).not.toContain("Your turn.");
      expect(html).not.toContain("<form");
      expect(html).not.toContain("<textarea");
    },
  );

  it("does not substitute the local module fixture for a direct module URL", async () => {
    const page = await ModulePage({
      params: Promise.resolve({
        programSlug: "free-course",
        moduleId: "module-02",
      }),
      searchParams: Promise.resolve({}),
    });
    const html = renderToStaticMarkup(page);

    expect(html).toContain("Module");
    expect(html).toContain("Preparing your workspace");
    expect(html).toContain('aria-busy="true"');
    expect(html).not.toContain('data-state="LOCKED"');
    expect(html).not.toContain("Module sequence");
    expect(html).not.toContain("Open first activity");
  });

  it("keeps API-backed activity navigation free of local fixture links", async () => {
    const activityPage = await ActivityPage({
      params: Promise.resolve({ activityId: "implement" }),
      searchParams: Promise.resolve({}),
    });
    const activityHtml = renderToStaticMarkup(activityPage);
    expect(activityHtml).toContain("Preparing your workspace");
    expect(activityHtml).toContain("surface-state__skeleton");
    expect(activityHtml).not.toContain('href="/activity/review"');
    expect(activityHtml).not.toContain('href="/activity/improve"');
  });
});

describe("typed course view models", () => {
  it("exposes the permanent hierarchy and exactly five first-slice activity kinds", () => {
    const activities = freeCourse.modules.flatMap(
      (courseModule) => courseModule.activities,
    );
    const kinds = activities.map((activity) => activity.kind);

    expect(freeCourse.slug).toBe("free-course");
    expect(freeCourse.modules).toHaveLength(2);
    expect(new Set(kinds)).toEqual(
      new Set([
        "VIDEO",
        "REFLECTION",
        "IMPLEMENTATION_CHALLENGE",
        "REVIEW",
        "IMPROVE",
      ]),
    );
    expect(new Set(activities.map((activity) => activity.id)).size).toBe(5);
    expect(getActivityById("review")?.kind).toBe("REVIEW");
  });
});

describe("honest preview controls", () => {
  it("renders activity seams without simulated saving, submission, playback, or captions", () => {
    const activities = freeCourse.modules.flatMap(
      (courseModule) => courseModule.activities,
    );
    const rendered = Object.fromEntries(
      activities.map((activity) => [
        activity.kind,
        renderToStaticMarkup(createElement(ActivityRenderer, { activity })),
      ]),
    );
    const allRenderers = Object.values(rendered).join(" ");

    expect(rendered.VIDEO).toContain("Media not connected");
    expect(rendered.VIDEO).not.toContain("<button");
    expect(rendered.VIDEO).not.toMatch(
      /CC captions available|Preview playing|Play the lesson preview/,
    );
    expect(rendered.REFLECTION).toContain('disabled=""');
    expect(rendered.IMPLEMENTATION_CHALLENGE).toContain('disabled=""');
    expect(rendered.REVIEW).toContain('disabled=""');
    expect(rendered.IMPROVE).toContain('disabled=""');
    expect(allRenderers).not.toMatch(
      /Save draft|Save attempt|Save review notes|Save next rep|acknowledged locally|captured in the preview/,
    );
  });

  it("keeps the onboarding conflict action explicit about editor review", () => {
    expect(ONBOARDING_USE_LOCAL_COPY_LABEL).toBe("Use local copy in editor");
    expect(ONBOARDING_USE_LOCAL_COPY_LABEL).not.toContain("Merge");
  });

  it("exposes connected password sign-in and waits for canonical onboarding state", () => {
    const login = renderToStaticMarkup(createElement(LoginForm));
    const onboarding = renderToStaticMarkup(createElement(OnboardingForm));

    expect(login).toContain("Sign in");
    expect(login).toContain('aria-label="Show password"');
    expect(login).toContain('autoComplete="current-password"');
    expect(login).toContain('href="/forgot-password"');
    expect(login).toContain('href="/register"');
    expect(login).toContain("Continue with Google");
    expect(login).toContain("First time here—including with Google?");
    expect(login).not.toContain("Email sign-in unavailable in preview");
    expect(onboarding).toContain("Loading your saved profile");
    expect(onboarding).not.toContain("Profile setup unavailable in preview");
    expect(onboarding).not.toContain("Choose the context");
  });

  it("hands unsupported localhost auth callbacks to canonical staging", () => {
    const login = renderToStaticMarkup(
      createElement(LoginForm, { stagingBridge: true }),
    );

    expect(login).toContain("Use your verified staging email and password");
    expect(login).toContain(
      'href="https://staging.authorityclosers.com/forgot-password"',
    );
    expect(login).toContain(
      'href="https://staging.authorityclosers.com/register"',
    );
    expect(login).toContain(
      "https://staging.authorityclosers.com/v1/auth/google/start",
    );
    expect(login).not.toContain('href="/forgot-password"');
    expect(login).not.toContain('href="/register"');
  });

  it("routes password sessions through canonical onboarding status", () => {
    expect(routeAfterOnboarding("not_started")).toBe("/onboarding");
    expect(routeAfterOnboarding("in_progress")).toBe("/onboarding");
    expect(routeAfterOnboarding("completed")).toBe("/home");
    expect(routeAfterOnboarding("skipped")).toBe("/home");
    expect(routeAfterOnboarding()).toBe("/onboarding");
  });

  it("allowlists onboarding return intent and preserves it in page transitions", async () => {
    expect(parseOnboardingReturnIntent("settings")).toBe("settings");
    expect(parseOnboardingReturnIntent(["settings", "/unsafe"])).toBe(
      "settings",
    );
    expect(parseOnboardingReturnIntent("settings%2Funsafe")).toBe("home");
    expect(parseOnboardingReturnIntent("unknown")).toBe("home");
    expect(onboardingReturnHref("settings")).toBe("/settings");
    expect(onboardingReturnHref("home")).toBe("/home");
    expect(onboardingHref("settings")).toBe("/onboarding?return=settings");
    expect(onboardingHref("home")).toBe("/onboarding");

    const settingsError = renderToStaticMarkup(
      await OnboardingPage({
        searchParams: Promise.resolve({
          state: "error-retryable",
          return: "settings",
        }),
      }),
    );
    expect(settingsError).toContain(
      'href="/onboarding?return=settings&amp;state=default"',
    );
    expect(settingsError).toContain('href="/settings"');
    expect(settingsError).toContain('aria-label="Back to settings"');

    const homeError = renderToStaticMarkup(
      await OnboardingPage({
        searchParams: Promise.resolve({
          state: "error-retryable",
          return: "not-allowlisted",
        }),
      }),
    );
    expect(homeError).toContain('href="/onboarding?state=default"');
    expect(homeError).toContain('href="/home"');
    expect(homeError).not.toContain("return=not-allowlisted");
  });

  it("exposes an accessible persisted appearance control", () => {
    const html = renderToStaticMarkup(createElement(ThemeControl));

    expect(html).toContain('aria-label="Appearance theme"');
    expect(html).toContain("Light");
    expect(html).toContain("Dark");
    expect(html).toContain("System");
    expect(html).not.toContain("Accent palette");
    expect(html.match(/aria-pressed=/g)).toHaveLength(3);
  });

  it("turns server-issued Google recovery results into safe learner actions", async () => {
    const consent = renderToStaticMarkup(
      await CallbackPage({
        searchParams: Promise.resolve({ result: "consent_required" }),
      }),
    );
    const registration = renderToStaticMarkup(
      await CallbackPage({
        searchParams: Promise.resolve({ result: "registration_required" }),
      }),
    );
    const consentUpdate = renderToStaticMarkup(
      await CallbackPage({
        searchParams: Promise.resolve({ result: "consent_update_required" }),
      }),
    );
    const unknown = renderToStaticMarkup(
      await CallbackPage({
        searchParams: Promise.resolve({ result: "not-a-result" }),
      }),
    );

    expect(consent).toContain("Confirm your learner access.");
    expect(consent).toContain('href="/register"');
    expect(consent).not.toContain("callback payload");
    expect(registration).toContain("This Google account is not linked yet.");
    expect(registration).toContain("will not create an account silently");
    expect(consentUpdate).toContain("Contact support");
    expect(consentUpdate).toContain("mailto:admin@authorityclosers.com");
    expect(consentUpdate).not.toContain('href="/register"');
    expect(consentUpdate).toContain('class="boundary-card"');
    expect(consentUpdate).not.toContain("boundary-card--dark");
    expect(unknown).toContain("Return to sign in");
    expect(unknown).not.toContain("not-a-result");
  });

  it("applies the Clarity Grid auth and onboarding compositions without changing capability", async () => {
    const registration = renderToStaticMarkup(createElement(RegisterPage));
    const verification = renderToStaticMarkup(createElement(VerifyEmailPage));
    const onboarding = renderToStaticMarkup(
      await OnboardingPage({ searchParams: Promise.resolve({}) }),
    );

    expect(registration).toContain('class="auth-main clarity-auth-main"');
    expect(registration).toContain("clarity-auth-shell--standard");
    expect(registration).toContain("clarity-auth-ledger");
    expect(registration.match(/is-outline/g)).toHaveLength(3);
    expect(registration).not.toContain('aria-current="step"');
    expect(registration).toContain("Create free account");
    expect(registration).toContain("action=register");
    expect(registration).toContain("Continue with Google");
    expect(registration).toContain('name="return_path" value="/onboarding"');
    expect(registration).not.toContain('name="return_path" value="/home"');
    expect(registration).toContain('name="consent"');
    expect(registration).toContain('value="true"');
    expect(registration.match(/type="checkbox"/g)).toHaveLength(1);
    expect(registration).not.toContain("Apple");
    expect(verification).toContain("one-time link");
    expect(verification).toContain("clarity-auth-masthead");
    expect(onboarding).toContain("clarity-auth-shell--onboarding");
    expect(onboarding).toContain("Make the course fit your work.");
    expect(onboarding).toContain("Skip to learning setup");
    expect(onboarding).toContain('aria-live="polite"');
    expect(onboarding.match(/is-outline/g) ?? []).toHaveLength(0);
    expect(onboarding).toContain("Loading setup");
    expect(onboarding).not.toContain('aria-current="step"');
    expect(onboarding).not.toContain("learner-sidebar");
  });
});

describe("click-first onboarding", () => {
  it("renders the ready goal question with semantic groups and a disabled empty state", () => {
    const html = renderToStaticMarkup(
      createElement<OnboardingFormProps>(OnboardingForm, {
        initialProfile: onboardingProfile(),
      }),
    );

    expect(html).not.toContain("Loading your saved profile");
    expect(html).toContain("What would you most like to improve?");
    expect(html).toContain('class="choice-fieldset"');
    expect(html).toContain('name="learning-goal"');
    expect(html).toContain('value="Handle objections with confidence"');
    expect(html).toContain('value="custom"');
    expect(html).toContain("Write a different goal");
    expect(html).toContain("Skip setup");
    expect(html).toContain('disabled=""');
    expect(html).not.toContain("aria-pressed");
  });

  it("enables Continue when a common goal is selected and preserves the saved contract value", () => {
    const html = renderToStaticMarkup(
      createElement<OnboardingFormProps>(OnboardingForm, {
        initialProfile: onboardingProfile({
          learning_goal: "Run clearer discovery calls",
        }),
      }),
    );

    expect(html).toContain(
      'name="learning-goal" checked="" value="Run clearer discovery calls"',
    );
    expect(html).toContain(">Continue");
    const submitButton =
      html.match(/<button[^>]*type="submit"[^>]*>[\s\S]*?<\/button>/)?.[0] ??
      "";
    expect(submitButton).not.toContain('disabled=""');
  });

  it("keeps live progress pending until onboarding state is known", () => {
    const html = renderToStaticMarkup(
      createElement(
        AuthFlowPage,
        {
          eyebrow: "Learning setup",
          heading: "Make the course fit your work.",
          copy: "Answer only what helps.",
          liveProgress: true,
          variant: "onboarding",
          steps: [
            { label: "Context", state: "upcoming" },
            { label: "Goal", state: "upcoming" },
            { label: "Optional details", state: "upcoming" },
          ],
        },
        "content",
      ),
    );

    expect(html).toContain("Loading setup");
    expect(html).not.toContain("Step 1 of 3");
    expect(html).toContain("Optional details");
    expect(html).not.toContain('aria-current="step"');
    expect(html.match(/clarity-auth-step-number/g) ?? []).toHaveLength(3);
    expect(html).toContain("clarity-auth-step-chevron");
    expect(authFlowStepState(1, 2)).toBe("complete");
    expect(authFlowStepState(2, 2)).toBe("current");
    expect(authFlowStepState(3, 2)).toBe("upcoming");
    expect(html).not.toContain("Step 4");
  });

  it("keeps detail answers optional inside step 3 and exposes compact labels", () => {
    const html = renderToStaticMarkup(
      createElement<OnboardingFormProps>(OnboardingForm, {
        initialProfile: onboardingProfile({
          current_step: 3,
          learning_goal: "Close more consistently",
        }),
      }),
    );

    expect(html).toContain("What situation are you working through?");
    expect(html).toContain("Optional");
    expect(html).toContain("A real conversation coming up");
    expect(html).toContain("Describe a different situation");
    expect(html).toContain("Skip setup");
    expect(html).not.toContain("Step 4 of 4");
  });

  it("keeps custom context input within the server field limit", () => {
    const html = renderToStaticMarkup(
      createElement<OnboardingFormProps>(OnboardingForm, {
        initialProfile: onboardingProfile({
          current_step: 1,
          experience_context: "leading a small sales team",
        }),
      }),
    );

    expect(html).toContain('id="experience-context-custom"');
    expect(html).toContain('maxLength="64"');
  });

  it("returns completed settings edits to the allowlisted settings surface", () => {
    const html = renderToStaticMarkup(
      createElement<OnboardingFormProps>(OnboardingForm, {
        initialProfile: onboardingProfile({
          status: "completed",
          current_step: 3,
        }),
        returnHref: "/settings",
      }),
    );

    expect(html).toContain("Your starting context is ready.");
    expect(html).toContain("Return to settings");
    expect(html).toContain('href="/settings"');
    expect(html).not.toContain('href="/home"');
  });

  it("keeps dirty recovery edits in the editor even after a completed server profile", () => {
    const serverDraft = {
      experienceContext: "sales",
      learningGoal: "Close more consistently",
      practiceSituation: "",
      weeklyMinutes: "",
    };
    const localDraft = {
      ...serverDraft,
      learningGoal: "Run clearer discovery calls",
    };

    expect(onboardingLocalDraftNeedsEditing(localDraft, serverDraft)).toBe(
      true,
    );
    expect(onboardingLocalDraftNeedsEditing(serverDraft, serverDraft)).toBe(
      false,
    );
  });

  it("enters the editor when a local recovery copy is merged from a completed profile", () => {
    const localDraft = {
      experienceContext: "sales",
      learningGoal: "Run clearer discovery calls",
      practiceSituation: "",
      weeklyMinutes: "",
    };

    expect(onboardingEditorStateFromLocalRecovery(localDraft, 2)).toEqual({
      finished: false,
      draft: localDraft,
      step: 2,
    });
  });

  it("serializes onboarding mutations and drops stale completions after unmount", () => {
    const lock = createOnboardingMutationLock();

    expect(lock.acquire()).toBe(false);
    lock.activate();
    expect(lock.acquire()).toBe(true);
    expect(lock.acquire()).toBe(false);
    lock.dispose();
    expect(lock.canCommit()).toBe(false);
    lock.release();
    expect(lock.acquire()).toBe(false);

    lock.activate();
    expect(lock.acquire()).toBe(true);
    expect(lock.canCommit()).toBe(true);
    lock.release();
  });

  it("renders cleanup-pending completion as a successful server save with recovery actions", () => {
    const html = renderToStaticMarkup(
      createElement(OnboardingCompletionState, {
        status: "completed",
        returnHref: "/settings",
        cleanupPending: true,
        cleanupAcknowledged: false,
        onRetryLocalCleanup: () => undefined,
        onCopyRecovery: () => undefined,
        onExportRecovery: () => undefined,
        onAcknowledgeRemainingCopy: () => undefined,
        onEdit: () => undefined,
      }),
    );

    expect(html).toContain('role="status"');
    expect(html).toContain("Saved on the server; local cleanup is pending.");
    expect(html).toContain("The server save succeeded.");
    expect(html).toContain("Retry local cleanup");
    expect(html).toContain("Copy recovery text");
    expect(html).toContain("Download recovery file");
    expect(html).toContain("Acknowledge remaining copy");
    expect(html).toContain('href="/settings"');
    expect(html).not.toContain("Profile save could not be completed");
  });

  it("surfaces a newer onboarding copy for cleanup retry and authorized discard", async () => {
    const storage = memoryStorage();
    const scope = { kind: "onboarding" as const, personId: "person-test" };
    const oldDraft = {
      experienceContext: "sales",
      learningGoal: "Old local answer",
      practiceSituation: "",
      weeklyMinutes: "",
    };
    const newerDraft = {
      ...oldDraft,
      learningGoal: "New local answer",
    };
    const oldNow = Date.UTC(2026, 8, 1, 12);
    const newerNow = oldNow + 1_000;
    writeOnboardingLocalDraft(storage, {
      scope,
      draft: oldDraft,
      baseRevision: 4,
      serverFingerprint: onboardingServerFingerprint(oldDraft),
      now: oldNow,
    });
    const oldCopy = peekOnboardingLocalDraftForCleanup(storage, scope, oldNow);
    expect(oldCopy.status).toBe("ready");
    if (oldCopy.status !== "ready") throw new Error("expected old copy");

    writeOnboardingLocalDraft(storage, {
      scope,
      draft: newerDraft,
      baseRevision: 4,
      serverFingerprint: onboardingServerFingerprint(oldDraft),
      now: newerNow,
    });
    const lockManager = exclusiveLockManager();
    const resolution = await reconcileOnboardingLocalCleanup(
      storage,
      scope,
      oldCopy.envelope,
      oldDraft,
      newerNow,
      lockManager,
    );

    expect(resolution).toMatchObject({
      result: { ok: false, reason: "changed" },
      newer: true,
      draft: newerDraft,
      envelope: { draft: newerDraft },
    });
    expect(
      storage.getItem("ac-learner-local-draft:onboarding:person-test"),
    ).not.toBeNull();

    const discard = await reconcileOnboardingLocalCleanup(
      storage,
      scope,
      resolution.envelope,
      newerDraft,
      newerNow,
      lockManager,
    );
    expect(discard).toMatchObject({
      result: { ok: true },
      newer: false,
      envelope: null,
      draft: null,
    });
    expect(
      storage.getItem("ac-learner-local-draft:onboarding:person-test"),
    ).toBeNull();
  });
});

describe("accessibility semantics", () => {
  it("renders exactly one h1 for every route template and universal state", async () => {
    for (const [routeName, renderRoute] of routeRenderers) {
      for (const state of SURFACE_STATE_ORDER) {
        const html = renderToStaticMarkup(await renderRoute(queryValue(state)));

        expect(h1Count(html), `${routeName} in ${state}`).toBe(1);
      }
    }
  }, 15_000);

  it("keeps the authenticated home empty of invented progress while the API loads", async () => {
    const html = renderToStaticMarkup(
      await LearnerHomePage({ searchParams: Promise.resolve({}) }),
    );

    expect(html).toContain("Learning Command Center");
    expect(html).toContain("dashboard-skeleton");
    expect(html).not.toContain("Open reflect preview");
    expect(html).not.toContain("preview only");
    expect(html).not.toContain('aria-valuenow="0"');
  });

  it("announces retryable errors as alerts with an honest retry action", () => {
    const html = renderToStaticMarkup(
      createElement(SurfaceStatePanel, {
        state: "ERROR_RETRYABLE",
        retryHref: "/learn/free-course",
      }),
    );

    expect(html).toContain('role="alert"');
    expect(html).toContain("This view did not finish loading");
    expect(html).toContain('href="/learn/free-course?state=default"');
    expect(html).toContain("Retry this view");
  });

  it("uses a live status for offline and success feedback states", () => {
    const offline = renderToStaticMarkup(
      createElement(SurfaceStatePanel, { state: "OFFLINE" }),
    );
    const success = renderToStaticMarkup(
      createElement(SurfaceStatePanel, { state: "SUCCESS_FEEDBACK" }),
    );

    expect(offline).toContain('role="status"');
    expect(offline).toContain("You are offline");
    expect(success).toContain('data-state="SUCCESS_FEEDBACK"');
    expect(success).toContain("Success feedback");
  });

  it("sends authenticated breadcrumbs home and exposes progress semantics", () => {
    const navigation = renderToStaticMarkup(
      createElement(Breadcrumbs, {
        items: [
          { label: "Course", href: "/learn/free-course" },
          { label: "Activity" },
        ],
      }),
    );
    const progress = renderToStaticMarkup(
      createElement(ProgressMeter, {
        value: 40,
        label: "Preview course path",
        detail: "2 / 5",
      }),
    );

    expect(navigation).toContain('aria-label="Breadcrumb"');
    expect(navigation).toContain('aria-label="Back to learner home"');
    expect(navigation).toContain('href="/home"');
    expect(navigation).toContain('aria-current="page"');
    expect(navigation.match(/aria-current=/g)).toHaveLength(1);
    expect(progress).toContain('role="progressbar"');
    expect(progress).toContain('aria-valuenow="40"');
    expect(progress).toContain('aria-valuemax="100"');
  });

  it("clamps the shared library progress meter to its declared range", () => {
    const progress = renderToStaticMarkup(
      createElement(ProgressMeter, {
        value: 140,
        label: "Preview course path",
        detail: "7 / 5",
      }),
    );

    expect(progress).toContain('aria-valuenow="100"');
    expect(progress).toContain('style="width:100%"');
  });

  it("preserves renderer labels while marking unavailable controls disabled", () => {
    const activities = freeCourse.modules.flatMap(
      (courseModule) => courseModule.activities,
    );
    const rendered = Object.fromEntries(
      activities.map((activity) => [
        activity.kind,
        renderToStaticMarkup(createElement(ActivityRenderer, { activity })),
      ]),
    );

    expect(rendered.VIDEO).toContain(
      'aria-label="Video integration preview; no media loaded"',
    );
    expect(rendered.VIDEO).toContain("Read sample transcript copy");
    expect(rendered.REFLECTION).toContain('for="reflection-response"');
    expect(rendered.REFLECTION).toContain('name="reflection"');
    expect(rendered.IMPLEMENTATION_CHALLENGE).toContain(
      "Choose the response that keeps the conversation honest.",
    );
    expect(rendered.IMPLEMENTATION_CHALLENGE).toContain('type="radio"');
    expect(rendered.REVIEW).toContain("Human-authored review");
    expect(rendered.REVIEW).toContain('type="checkbox"');
    expect(rendered.IMPROVE).toContain('for="improve-after"');
    expect(rendered.IMPROVE).toContain("What will you try next?");
  });

  it("uses exactly one page-level heading on the certificate route", async () => {
    const page = await CertificatePage({
      params: Promise.resolve({ certificateId: "preview-certificate" }),
      searchParams: Promise.resolve({}),
    });
    const html = renderToStaticMarkup(page);

    expect(html.match(/<h1(?:\s|>)/g)).toHaveLength(1);
    expect(html).toContain("Certificate");
    expect(html).toContain("Preparing your workspace");
    expect(html).toContain('aria-busy="true"');
    expect(html).not.toContain("preview-certificate · issued");
  });
});

describe("connected learner ready states", () => {
  const baseActivity: ActivityResponse = {
    id: "activity-1",
    module_id: "module-1",
    program_version_id: "version-1",
    position: 1,
    kind: "REFLECTION",
    title: "A server-owned activity title",
    prompt: null,
    state: "available",
    revision: 5,
    required: true,
    explanation: {
      activity_id: "activity-1",
      state: "available",
      required: true,
      reason: "server_resolved_activity_state",
      missing_activity_ids: [],
      missing_module_ids: [],
    },
    allowed_actions: [],
    program_id: "program-1",
    enrollment_id: "enrollment-1",
    draft_revision: 0,
    draft_payload: null,
  };

  it("serializes activity operations and invalidates stale completions", () => {
    const lock = createActivityOperationLock();
    lock.activate();
    const first = lock.acquire();
    expect(first).not.toBeNull();
    expect(lock.acquire()).toBeNull();
    expect(lock.canCommit(first as number)).toBe(true);

    lock.invalidate();
    expect(lock.canCommit(first as number)).toBe(false);
    const second = lock.acquire();
    expect(second).not.toBeNull();
    lock.release(first as number);
    expect(lock.canCommit(second as number)).toBe(true);
    lock.dispose();
    expect(lock.canCommit(second as number)).toBe(false);
    lock.release(second as number);
  });

  it("hides cleanup state from a prior activity when a reused surface changes scope", () => {
    expect(
      activityStateForScope(
        {
          scopeKey: '"tenant-1","person-1","enrollment-1","activity-1"',
          value: "old cleanup",
        },
        '"tenant-1","person-1","enrollment-1","activity-2"',
      ),
    ).toBeNull();
    expect(
      activityStateForScope(
        {
          scopeKey: '"tenant-1","person-1","enrollment-1","activity-2"',
          value: "current cleanup",
        },
        '"tenant-1","person-1","enrollment-1","activity-2"',
      ),
    ).toBe("current cleanup");
  });

  it("keeps production recovery callers on locked async paths", () => {
    const runtimeSource = readFileSync(
      new URL("../components/learner-runtime.tsx", import.meta.url),
      "utf8",
    );
    const onboardingSource = readFileSync(
      new URL("../components/onboarding-form.tsx", import.meta.url),
      "utf8",
    );
    expect(runtimeSource).toContain("readActivityLocalDraftWithLock");
    expect(runtimeSource).toContain("writeActivityLocalDraftWithLock");
    expect(runtimeSource).toContain("clearActivityLocalDraftIfMatchesWithLock");
    expect(runtimeSource).toContain("purgeActivityLocalDraftIfMatchesWithLock");
    expect(runtimeSource).not.toMatch(/\breadActivityLocalDraft\(/);
    expect(runtimeSource).not.toMatch(/\bwriteActivityLocalDraft\(/);
    expect(runtimeSource).not.toMatch(/\bclearActivityLocalDraft\(/);
    expect(onboardingSource).toContain("readOnboardingLocalDraftWithLock");
    expect(onboardingSource).toContain("reconcileOnboardingLocalCleanup");
    expect(
      onboardingSource.match(/reconcileOnboardingLocalCleanup/g)?.length ?? 0,
    ).toBeGreaterThanOrEqual(4);
    expect(onboardingSource).toContain(
      "purgeOnboardingLocalDraftIfMatchesWithLock",
    );
    expect(onboardingSource).not.toMatch(/\bclearOnboardingLocalDraft\(/);
  });

  it("keeps Next scroll behavior and Settings route-entry focus contracts explicit", () => {
    const layoutSource = readFileSync(
      new URL("../layout.tsx", import.meta.url),
      "utf8",
    );
    const settingsSource = readFileSync(
      new URL("../components/settings-runtime.tsx", import.meta.url),
      "utf8",
    );
    const settingsCssSource = readFileSync(
      new URL("../components/settings-clarity.module.css", import.meta.url),
      "utf8",
    );
    expect(layoutSource).toContain('data-scroll-behavior="smooth"');
    expect(settingsSource).toContain('id="settings-title"');
    expect(settingsSource).toContain("routeEntryHeadingRef.current?.focus()");
    expect(settingsCssSource).toContain(".routeEntryHeading:focus");
    expect(settingsCssSource).toContain("outline: none");
    expect(settingsCssSource).toContain(".indexLink:focus-visible");
  });

  it("defers the initial Calendar load while retaining cancellation guards", () => {
    const calendarSource = readFileSync(
      new URL("../components/calendar-runtime.tsx", import.meta.url),
      "utf8",
    );
    expect(calendarSource).toContain("async function loadInitial()");
    expect(calendarSource).toContain("await Promise.resolve();");
    expect(calendarSource).toContain("controller.abort();");
    expect(calendarSource).not.toContain("void load(controller.signal)");
  });

  it("starts only identity and authoritative activity reads together", async () => {
    const started: string[] = [];
    const api = {
      me: async () => {
        started.push("me");
        return {
          person_id: "person-1",
          email: "learner@example.com",
          display_name: "Learner",
          email_verified_at: "2026-08-31T00:00:00Z",
          selected_tenant_id: "tenant-1",
          membership_role: "learner",
          permissions: [],
        } satisfies MeResponse;
      },
      activity: async () => {
        started.push("activity");
        return baseActivity;
      },
    } as unknown as LearnerApi;

    await expect(
      loadActivityEntryState("activity-1", api),
    ).resolves.toMatchObject({
      activity: { id: "activity-1", program_id: "program-1" },
    });
    expect(started).toEqual(["me", "activity"]);
  });

  it("rejects a learning path from a different enrollment or version", () => {
    const matching = {
      program_id: "program-1",
      program_version_id: "version-1",
      enrollment_id: "enrollment-1",
    } as LearningResponse;
    expect(learningPathMatchesActivity(matching, baseActivity)).toBe(true);
    expect(
      learningPathMatchesActivity(
        { ...matching, enrollment_id: "enrollment-2" },
        baseActivity,
      ),
    ).toBe(false);
    expect(
      learningPathMatchesActivity(
        { ...matching, program_version_id: "superseded-version" },
        baseActivity,
      ),
    ).toBe(false);
  });

  it("refreshes authoritative activity and learning snapshots together after a mutation", async () => {
    const nextActivity = {
      ...baseActivity,
      state: "awaiting_review",
      revision: 6,
    };
    const nextLearning = {
      program_id: "program-1",
      program_version_id: "version-1",
      program_slug: FREE_COURSE_SLUG,
      program_title: "Authority Closers Free Course",
      version_number: 1,
      enrollment_id: "enrollment-1",
      modules: [],
      projection: {
        scope_type: "program",
        scope_id: "program-1",
        program_version: "version-1",
        projection_version: "v1",
        denominator: 5,
        completed_count: 1,
        percentage: 0.2,
        predicate: "required activities completed",
        missing_module_ids: [],
        activity_reasons: [],
      },
    } satisfies LearningResponse;
    const api = {
      activity: vi.fn(async () => nextActivity),
      learning: vi.fn(async () => nextLearning),
    } as unknown as LearnerApi;

    await expect(
      refreshActivityLearningSnapshots(baseActivity, api),
    ).resolves.toEqual({ activity: nextActivity, learning: nextLearning });
    expect(api.activity).toHaveBeenCalledWith("activity-1");
    expect(api.learning).toHaveBeenCalledWith("program-1", {
      enrollmentId: "enrollment-1",
      programVersionId: "version-1",
    });
  });

  it("loads learner home only from the exact Free Course program identity", async () => {
    const learning = {
      program_id: "program-1",
      program_version_id: "version-1",
      program_slug: FREE_COURSE_SLUG,
      program_title: "Authority Closers Free Course",
      version_number: 1,
      enrollment_id: "enrollment-1",
      modules: [],
      projection: {
        scope_type: "program",
        scope_id: "program-1",
        program_version: "version-1",
        projection_version: "v1",
        denominator: 5,
        completed_count: 0,
        percentage: 0,
        predicate: "required activities completed",
        missing_module_ids: [],
        activity_reasons: [],
      },
    } satisfies LearningResponse;
    const api = {
      me: async () => ({
        person_id: "person-1",
        email: "learner@example.com",
        display_name: "Learner",
        email_verified_at: "2026-08-31T00:00:00Z",
        selected_tenant_id: "tenant-1",
        membership_role: "learner",
        permissions: [],
      }),
      context: async () => ({
        person_id: "person-1",
        session_id: "session-1",
        tenant_id: "tenant-1",
        membership_role: "learner",
        permissions: [],
      }),
      listPrograms: async () => ({
        items: [
          {
            id: "program-1",
            slug: FREE_COURSE_SLUG,
            title: "Authority Closers Free Course",
            program_version_id: "version-1",
            version_number: 1,
            published_at: "2026-08-31T00:00:00Z",
          },
        ],
        next_cursor: null,
      }),
      learning: async (programId: string) => {
        expect(programId).toBe("program-1");
        return learning;
      },
    } as unknown as LearnerApi;

    await expect(identityState(api)).resolves.toMatchObject({ learning });
  });

  it("does not probe title matches or the first accessible program", async () => {
    const learning = vi.fn();
    const api = {
      me: async () => ({
        person_id: "person-1",
        email: "learner@example.com",
        display_name: "Learner",
        email_verified_at: "2026-08-31T00:00:00Z",
        selected_tenant_id: "tenant-1",
        membership_role: "learner",
        permissions: [],
      }),
      context: async () => ({
        person_id: "person-1",
        session_id: "session-1",
        tenant_id: "tenant-1",
        membership_role: "learner",
        permissions: [],
      }),
      listPrograms: async () => ({
        items: [
          {
            id: "title-impostor",
            slug: "not-the-free-course",
            title: "Authority Closers Free Course",
            program_version_id: "other-version",
            version_number: 1,
            published_at: "2026-08-31T00:00:00Z",
          },
        ],
        next_cursor: null,
      }),
      learning,
    } as unknown as LearnerApi;

    await expect(identityState(api)).resolves.toMatchObject({
      learning: undefined,
    });
    expect(learning).not.toHaveBeenCalled();
  });

  it("keeps activity controls disabled when the server has no prompt", () => {
    const html = renderToStaticMarkup(
      createElement(ConnectedActivityWorkspace, {
        activity: {
          ...baseActivity,
          prompt: null,
          allowed_actions: ["save_draft", "submit_evidence"],
        },
      }),
    );

    expect(html).toContain("No learner prompt is published for this activity.");
    expect(html).toContain('id="activity-response"');
    expect(html.match(/disabled=""/g)).toHaveLength(3);
    expect(html).not.toContain('class="prompt-card"');
  });

  it("restores a server draft and enables only a prompted available activity", () => {
    const html = renderToStaticMarkup(
      createElement(ConnectedActivityWorkspace, {
        activity: {
          ...baseActivity,
          position: 2,
          prompt: "Describe the next deliberate move.",
          state: "in_progress",
          draft_revision: 3,
          draft_payload: { response: "Restored server draft" },
          allowed_actions: ["save_draft"],
        },
      }),
    );

    expect(html).toContain("Describe the next deliberate move.");
    expect(html).toContain("Restored server draft");
    expect(html).toContain("Current activity");
    expect(html).toContain("Step 2");
    expect(html).not.toContain("1 of 1");
    expect(html).toContain("Save reflection");
    expect(html).toContain("Server draft restored");
    expect(html).toContain("Versioned learner draft");
    expect(html).not.toContain("No learner-facing prompt is published.");
    expect(html).not.toContain('id="activity-response" disabled=""');
    expect(html).not.toContain('type="submit" disabled=""');
    expect(html).toMatch(/type="button"[^>]*disabled=""/);
  });

  it("keeps all mutations disabled when the server exposes no allowed action", () => {
    const html = renderToStaticMarkup(
      createElement(ConnectedActivityWorkspace, {
        activity: {
          ...baseActivity,
          prompt: "A prompt alone is not authorization.",
          allowed_actions: [],
        },
      }),
    );

    expect(html).toContain("A prompt alone is not authorization.");
    expect(html).toMatch(/id="activity-response"[^>]*disabled=""/);
    expect(html.match(/disabled=""/g)).toHaveLength(3);
  });

  it("renders locked server activities without navigable links", () => {
    const locked = renderToStaticMarkup(
      createElement(LearningActivityNavigation, {
        activity: {
          ...baseActivity,
          prompt: null,
          state: "locked",
          allowed_actions: [],
        },
      }),
    );
    const available = renderToStaticMarkup(
      createElement(LearningActivityNavigation, {
        activity: {
          ...baseActivity,
          prompt: "Server-owned prompt",
          state: "available",
          allowed_actions: ["save_draft"],
        },
      }),
    );

    expect(locked).toContain('aria-disabled="true"');
    expect(locked).not.toContain("href=");
    expect(available).toContain('href="/activity/activity-1"');
  });

  function learningModulesFixture(): LearningResponse {
    const activity = (
      id: string,
      moduleId: string,
      position: number,
      state: string,
      title: string,
    ) => ({
      ...baseActivity,
      id,
      module_id: moduleId,
      position,
      title,
      state,
      explanation: {
        ...baseActivity.explanation,
        activity_id: id,
        state,
        missing_activity_ids: state === "locked" ? ["earlier-required"] : [],
      },
    });
    return {
      program_id: "program-1",
      program_version_id: "version-1",
      program_slug: "server-owned-learning-path",
      program_title: "An explicitly enrolled course",
      version_number: 1,
      enrollment_id: "enrollment-1",
      modules: [
        {
          id: "locked-chapter",
          position: 1,
          title: "Opening decisions",
          activities: [
            activity(
              "locked-step",
              "locked-chapter",
              1,
              "locked",
              "A gated opening",
            ),
          ],
        },
        {
          id: "current-chapter",
          position: 4,
          title: "Discovery decisions",
          activities: [
            activity(
              "finished-step",
              "current-chapter",
              2,
              "completed",
              "A completed reflection",
            ),
            activity(
              "review-step",
              "current-chapter",
              5,
              "awaiting_review",
              "A submitted reflection",
            ),
            activity(
              "available-step",
              "current-chapter",
              8,
              "available",
              "The next question",
            ),
          ],
        },
        {
          id: "empty-chapter",
          position: 9,
          title: "A not-yet-published chapter",
          activities: [],
        },
      ],
      projection: {
        scope_type: "course",
        scope_id: "program-1",
        program_version: "1",
        projection_version: "1",
        denominator: 12,
        completed_count: 1,
        percentage: 1 / 12,
        predicate: "required activities completed",
        missing_module_ids: ["locked-chapter", "current-chapter"],
        activity_reasons: [],
      },
    };
  }

  it("renders the mounted course outline in server order with exact activity and module routes", () => {
    const learning = learningModulesFixture();
    const before = JSON.stringify(learning);
    const html = renderToStaticMarkup(
      createElement(LearningModules, { learning }),
    );
    const titles = [
      "Opening decisions",
      "A gated opening",
      "Discovery decisions",
      "A completed reflection",
      "A submitted reflection",
      "The next question",
      "A not-yet-published chapter",
    ];
    const offsets = titles.map((title) => html.indexOf(title));
    expect(offsets.every((offset) => offset >= 0)).toBe(true);
    expect(offsets).toEqual([...offsets].sort((a, b) => a - b));
    const hrefs = [...html.matchAll(/href="([^"]+)"/g)].map(
      (match) => match[1],
    );
    expect(hrefs).toEqual([
      ROUTES.activity("finished-step"),
      ROUTES.activity("review-step"),
      ROUTES.activity("available-step"),
      ROUTES.module(learning.program_slug, "current-chapter"),
    ]);
    expect(JSON.stringify(learning)).toBe(before);
    expect(html).not.toContain("authority-closers-free-course");
  });

  it("does not make locked or unpublished chapters navigable", () => {
    const learning = learningModulesFixture();
    const html = renderToStaticMarkup(
      createElement(LearningModules, { learning }),
    );
    expect(html).toContain('aria-disabled="true"');
    expect(html).toContain("Complete 1 earlier required activity to unlock.");
    expect(html).not.toContain(`href="${ROUTES.activity("locked-step")}"`);
    expect(html).not.toContain(
      `href="${ROUTES.module(learning.program_slug, "locked-chapter")}"`,
    );
    expect(html).not.toContain(
      `href="${ROUTES.module(learning.program_slug, "empty-chapter")}"`,
    );
    expect(html).toContain("No activities are published for this module yet.");
  });

  it("opens the first actionable chapter and preserves the other native disclosures", () => {
    const html = renderToStaticMarkup(
      createElement(LearningModules, { learning: learningModulesFixture() }),
    );
    const chapters = [
      ...html.matchAll(/<details([^>]*)>([\s\S]*?)<\/details>/g),
    ];
    expect(chapters).toHaveLength(3);
    expect(chapters[0][1]).not.toMatch(/\bopen\b/);
    expect(chapters[1][1]).toMatch(/\bopen\b/);
    expect(chapters[2][1]).not.toMatch(/\bopen\b/);
    for (const chapter of chapters) expect(chapter[2]).toContain("<summary");
    expect(chapters[1][2]).toContain("Discovery decisions");
    expect(chapters[1][2]).toContain("1 of 3 activities complete");
    expect(chapters[1][2]).not.toContain("2 of 3 activities complete");
    expect(chapters[1][2]).not.toContain("· Available");
  });

  it("keeps the primary continue action on the canonical actionable activity", () => {
    const learning = learningModulesFixture();
    expect(learningPathContinueTarget(learning)).toEqual({
      href: ROUTES.activity("available-step"),
      label: "Continue learning",
    });
    learning.modules[1].activities[1].state = "in_progress";
    expect(learningPathContinueTarget(learning)).toEqual({
      href: ROUTES.activity("review-step"),
      label: "Continue learning",
    });
  });

  it("uses a reviewable chapter rather than a locked first chapter when no activity is actionable", () => {
    const learning = learningModulesFixture();
    learning.modules[1].activities[2].state = "locked";
    expect(learningPathContinueTarget(learning)).toEqual({
      href: ROUTES.module(learning.program_slug, "current-chapter"),
      label: "Open Module 4",
    });
  });

  it.each(["locked", "unpublished", "empty"])(
    "keeps the primary action in the outline when all course content is %s",
    (state) => {
      const learning = learningModulesFixture();
      if (state === "empty") learning.modules = [];
      else {
        for (const chapter of learning.modules) {
          if (state === "unpublished") chapter.activities = [];
          else
            for (const activity of chapter.activities)
              activity.state = "locked";
        }
      }
      expect(learningPathContinueTarget(learning)).toEqual({
        href: "#course-outline-title",
        label: "View course outline",
      });
    },
  );

  it("keeps review-pending navigation readable without pretending that no mutation means locked", () => {
    const activity = learningModulesFixture().modules[1].activities[1];
    expect(activity.allowed_actions).toEqual([]);
    const html = renderToStaticMarkup(
      createElement(LearningActivityNavigation, { activity }),
    );
    expect(html).toContain(`href="${ROUTES.activity(activity.id)}"`);
    expect(html).toMatch(/awaiting review/i);
    expect(html).not.toContain('aria-disabled="true"');
    expect(html).not.toMatch(/\bcompleted\b/i);
  });

  it("keeps ready activity rows action-first without repeating a ready label", () => {
    const activity = learningModulesFixture().modules[1].activities[2];
    const html = renderToStaticMarkup(
      createElement(LearningActivityNavigation, { activity }),
    );

    expect(html).toContain(`href="${ROUTES.activity(activity.id)}"`);
    expect(html).not.toMatch(/>Available<|>available<|· Available/);
  });

  it("removes both activity and chapter links for a cached learning response", () => {
    const learning = markOfflineRead(learningModulesFixture(), 7_000);
    const html = renderToStaticMarkup(
      createElement(LearningModules, { learning }),
    );
    expect(html).toMatch(/reconnect/i);
    expect(html).toContain('aria-disabled="true"');
    expect(html).not.toContain("href=");
    expect(html).toContain("Discovery decisions");
    expect(html).toContain("The next question");
  });

  it("blocks a fresh outline when the enclosing identity or program read is offline", () => {
    const learning = learningModulesFixture();
    const html = renderToStaticMarkup(
      createElement(LearningModules, { learning, disabled: true }),
    );
    expect(html).toMatch(/reconnect/i);
    expect(html).not.toContain("href=");
    expect(html).toContain("A completed reflection");
  });

  it.each(["available", "in_progress", "completed", "awaiting_review"])(
    "does not allow an offline %s activity to regain a link from its state",
    (state) => {
      const activity = markOfflineRead({ ...baseActivity, state }, 7_000);
      const html = renderToStaticMarkup(
        createElement(LearningActivityNavigation, { activity }),
      );
      expect(html).toContain('aria-disabled="true"');
      expect(html).toMatch(/reconnect/i);
      expect(html).not.toContain("href=");
    },
  );

  it("does not invent chapters, progress, rewards or recognition for an empty outline", () => {
    const learning = { ...learningModulesFixture(), modules: [] };
    const html = renderToStaticMarkup(
      createElement(LearningModules, { learning }),
    );
    expect(html).not.toContain("href=");
    expect(html).not.toContain("Module 1");
    expect(html).not.toMatch(
      /\b(?:XP|streak|mastery|achievement|badge)\b|100%|certificate earned/i,
    );
    expect(learning.projection.completed_count).toBe(1);
    expect(learning.projection.denominator).toBe(12);
  });

  it("shows the published Free Course until an enrollment is selected", () => {
    const program = {
      id: "program-1",
      slug: "authority-closers-free-course",
      title: "Authority Closers Free Course",
      program_version_id: "version-1",
      version_number: 1,
      published_at: "2026-08-31T00:00:00Z",
    };
    const html = renderToStaticMarkup(
      createElement(LearnerHomeEnrollmentCard, {
        learning: undefined,
        program,
      }),
    );

    expect(html).toContain("Authority Closers Free Course");
    expect(html).toContain("Start free course");
    expect(html).toContain('href="/programs/authority-closers-free-course"');
    expect(html).not.toMatch(/projection unavailable|assignment collection/i);
  });

  it("selects only the published Authority Closers Free Course", () => {
    const other = {
      id: "other",
      slug: "other",
      title: "Another Program",
      program_version_id: "other-version",
      version_number: 1,
      published_at: "2026-08-31T00:00:00Z",
    };
    const freeCourse = {
      ...other,
      id: "free",
      slug: "authority-closers-free-course",
      title: "Authority Closers Free Course",
    };

    expect(selectPublishedFreeCourse([other, freeCourse])).toBe(freeCourse);
    expect(selectPublishedFreeCourse([other])).toBeUndefined();
    expect(
      selectPublishedFreeCourse([
        { ...other, title: "Authority Closers Free Course" },
      ]),
    ).toBeUndefined();
    expect(isFreeEnrollmentProgram(freeCourse)).toBe(true);
    expect(isFreeEnrollmentProgram(other)).toBe(false);
  });

  it("gates protected learner content when membership role is missing", async () => {
    const me = {
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Learner",
      email_verified_at: "2026-08-31T00:00:00Z",
      selected_tenant_id: null,
      membership_role: null,
      permissions: [],
    };
    const learning = vi.fn();
    const api = {
      me: async () => me,
      context: async () => ({
        person_id: "person-1",
        session_id: "session-1",
        tenant_id: null,
        membership_role: null,
        permissions: [],
      }),
      listPrograms: async () => ({
        items: [
          {
            id: "program-1",
            slug: FREE_COURSE_SLUG,
            title: "Authority Closers Free Course",
            program_version_id: "version-1",
            version_number: 1,
            published_at: "2026-08-31T00:00:00Z",
          },
        ],
        next_cursor: null,
      }),
      learning,
    } as unknown as LearnerApi;

    await expect(identityState(api)).resolves.toMatchObject({
      me,
      learning: undefined,
    });
    expect(hasMembershipRole(me)).toBe(false);
    expect(learning).not.toHaveBeenCalled();

    const unavailable = renderToStaticMarkup(
      createElement(MembershipUnavailable),
    );
    expect(unavailable).toContain("Learner membership is unavailable.");
    expect(unavailable).toContain('role="alert"');
    expect(unavailable).not.toContain("Learner profile");
    const cleanupFailure = renderToStaticMarkup(
      createElement(MembershipDraftCleanupNotice, {
        cleanup: { status: "failed", retry: () => undefined },
      }),
    );
    expect(cleanupFailure).toContain("could not complete");
    expect(cleanupFailure).toContain("Retry local cleanup");
    expect(learnerHomeMode(false, false)).toBe("activation");
    expect(learnerHomeMode(false, true)).toBe("activation");
    expect(learnerHomeMode(true, false)).toBe("onboarding");
    expect(learnerHomeMode(true, true)).toBe("workspace");
  });

  it.each(["owner", "admin", "support"])(
    "gates protected learner content for the %s role",
    (membershipRole) => {
      const me: MeResponse = {
        person_id: "privileged-person-1",
        email: "privileged@example.test",
        display_name: "Privileged member",
        email_verified_at: "2026-09-01T00:00:00Z",
        selected_tenant_id: "public-learner-tenant-1",
        membership_role: membershipRole,
        permissions: [],
      };

      expect(hasMembershipRole(me)).toBe(false);
    },
  );

  it("allows protected learner content only for the exact learner role", () => {
    const me: MeResponse = {
      person_id: "learner-person-1",
      email: "learner@example.test",
      display_name: "Learner",
      email_verified_at: "2026-09-01T00:00:00Z",
      selected_tenant_id: "public-learner-tenant-1",
      membership_role: "learner",
      permissions: [],
    };

    expect(hasMembershipRole(me)).toBe(true);
  });

  it("renders sign-out failure as an alert with a retry", () => {
    const message = signOutFailureMessage(new TypeError("offline"));
    const html = renderToStaticMarkup(
      createElement(SignOutFailure, { message, retry: () => undefined }),
    );
    expect(html).toContain('role="alert"');
    expect(html).toContain("Retry sign out");
    expect(html).toContain("Check your connection");
  });

  it("keeps enrollment failure recovery explicit and policy-gated", () => {
    expect(enrollmentFailureMessage(new ApiError(401, "expired"))).toEqual({
      message: "Your session expired before the course could start.",
      recoveryHref: "/session-expired",
      recoveryLabel: "Sign in again",
    });
    expect(
      enrollmentFailureMessage(
        new ApiError(403, "context unavailable", {
          code: "tenant_context_required",
        }),
      ),
    ).toEqual({
      message:
        "Learner access could not be activated automatically. Your account and existing progress were not changed.",
      recoveryHref:
        "mailto:admin@authorityclosers.com?subject=Authority%20Closers%20learner%20access",
      recoveryLabel: "Contact learner support",
    });
    expect(
      enrollmentFailureMessage(
        new ApiError(403, "not eligible", {
          code: "self_attested_eligibility_denied",
        }),
      ),
    ).toEqual({
      message:
        "Free-course access could not be confirmed for this account. Your account and existing progress were not changed.",
      recoveryHref:
        "mailto:admin@authorityclosers.com?subject=Authority%20Closers%20learner%20access",
      recoveryLabel: "Contact learner support",
    });
  });

  it("does not expose guessed course, certificate, or preview identity navigation", () => {
    const html = renderToStaticMarkup(
      createElement(LearnerShell, { current: "course" }, "content"),
    );

    expect(html).not.toContain("free-course");
    expect(html).not.toContain("preview-certificate");
    expect(html).not.toContain("Preview identity");
    expect(html).not.toContain('aria-disabled="true"');
    expect(html).not.toContain("Practice");
    expect(html).not.toContain("Library");
    expect(html).not.toContain("Search is coming later");
    expect(html).not.toContain('href="/home#practice"');
    expect(html).toContain('href="/progress"');
    expect(html).toContain('href="/settings"');
  });
});
