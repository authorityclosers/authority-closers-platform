import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import ActivityPage from "../activity/[activityId]/page";
import CallbackPage from "../auth/callback/page";
import CertificatePage from "../certificates/[certificateId]/page";
import { ActivityRenderer } from "../components/activity-renderers";
import {
  ConnectedActivityWorkspace,
  LearningActivityNavigation,
  LearnerHomeEnrollmentCard,
} from "../components/learner-runtime";
import { LoginForm } from "../components/login-form";
import { OnboardingForm } from "../components/onboarding-form";
import { ActivityStatusPill, ProgressMeter } from "../components/shared-ui";
import { Breadcrumbs, LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import LearnerHomePage from "../home/page";
import ProgramLearningPage from "../learn/[programSlug]/page";
import CompletionPage from "../learn/[programSlug]/complete/page";
import ModulePage from "../learn/[programSlug]/module/[moduleId]/page";
import LoginPage from "../login/page";
import ForgotPasswordPage from "../forgot-password/page";
import manifest from "../manifest";
import OfflinePage from "../offline/page";
import OnboardingPage from "../onboarding/page";
import PublicHomePage from "../page";
import PrivacyPage from "../privacy/page";
import ProgramDetailPage from "../programs/[slug]/page";
import RegisterPage from "../register/page";
import ResetPasswordPage from "../reset-password/page";
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
  parseSurfaceState,
  stateQuery,
  SURFACE_STATE_ORDER,
  type SurfaceState,
} from "./surface-state";
import type { ActivityResponse } from "./learner-api";

function h1Count(html: string): number {
  return html.match(/<h1(?:\s|>)/g)?.length ?? 0;
}

function queryValue(state: SurfaceState): string | undefined {
  return state === "DEFAULT"
    ? undefined
    : state.toLowerCase().replaceAll("_", "-");
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
    expect(metadata.name).toBe("Authority Closers Learning");
    expect(metadata.icons).toEqual([
      expect.objectContaining({
        src: "/icon-192.png",
        sizes: "192x192",
        purpose: "any",
      }),
      expect.objectContaining({
        src: "/icon-512.png",
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
      expect(html).toContain("Loading server data");
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
    expect(html).toContain("Loading server data");
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
    expect(activityHtml).toContain("Loading server data");
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

  it("exposes connected password sign-in and waits for canonical onboarding state", () => {
    const login = renderToStaticMarkup(createElement(LoginForm));
    const onboarding = renderToStaticMarkup(createElement(OnboardingForm));

    expect(login).toContain("Sign in");
    expect(login).toContain('aria-label="Show password"');
    expect(login).toContain('autoComplete="current-password"');
    expect(login).toContain('href="/forgot-password"');
    expect(login).toContain('href="/register"');
    expect(login).not.toContain("Email sign-in unavailable in preview");
    expect(onboarding).toContain("Loading your saved profile");
    expect(onboarding).not.toContain("Profile setup unavailable in preview");
    expect(onboarding).not.toContain("Choose the context");
  });

  it("applies the Clarity Grid auth and onboarding compositions without changing capability", async () => {
    const registration = renderToStaticMarkup(createElement(RegisterPage));
    const verification = renderToStaticMarkup(createElement(VerifyEmailPage));
    const onboarding = renderToStaticMarkup(
      await OnboardingPage({ searchParams: Promise.resolve({}) }),
    );

    expect(registration).toContain('class="auth-main clarity-auth-main"');
    expect(registration).toContain("auth-workspace-lake-v1.png");
    expect(registration).toContain("Create free account");
    expect(registration).toContain("action=register");
    expect(registration).toContain("Continue with Google");
    expect(registration).toContain('name="consent"');
    expect(registration).toContain('value="true"');
    expect(registration.match(/type="checkbox"/g)).toHaveLength(1);
    expect(registration).not.toContain("Apple");
    expect(verification).toContain("one-time link");
    expect(verification).toContain("clarity-auth-brand-media");
    expect(onboarding).toContain(
      'class="learner-main auth-main clarity-onboarding-main"',
    );
    expect(onboarding).toContain("clarity-onboarding-steps");
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
  });

  it("keeps the authenticated home empty of invented progress while the API loads", async () => {
    const html = renderToStaticMarkup(
      await LearnerHomePage({ searchParams: Promise.resolve({}) }),
    );

    expect(html).toContain("Learner workspace");
    expect(html).toContain("Loading server data");
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
    expect(html).toContain("Loading server data");
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
    enrollment_id: "enrollment-1",
    draft_revision: 0,
    draft_payload: null,
  };

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

    expect(html).toContain("No learner-facing prompt is published.");
    expect(html).toContain('id="activity-response"');
    expect(html.match(/disabled=""/g)).toHaveLength(3);
    expect(html).not.toContain('class="prompt-card"');
  });

  it("restores a server draft and enables only a prompted available activity", () => {
    const html = renderToStaticMarkup(
      createElement(ConnectedActivityWorkspace, {
        activity: {
          ...baseActivity,
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
    expect(html).toContain("Module 1 learning loop");
    expect(html).toContain("Server draft restored");
    expect(html).toContain("Controlled learner draft");
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

  it("shows no current course until the server selects an enrollment", () => {
    const html = renderToStaticMarkup(
      createElement(LearnerHomeEnrollmentCard, { learning: undefined }),
    );

    expect(html).toContain("No current course selected.");
    expect(html).toContain("absence of a projection is not treated as proof");
    expect(html).toContain('href="/"');
    expect(html).not.toContain("/learn/free-course");
  });

  it("does not expose guessed course, certificate, or preview identity navigation", () => {
    const html = renderToStaticMarkup(
      createElement(LearnerShell, { current: "course" }, "content"),
    );

    expect(html).not.toContain("free-course");
    expect(html).not.toContain("preview-certificate");
    expect(html).not.toContain("Preview identity");
    expect(html.match(/aria-disabled="true"/g)).toHaveLength(8);
  });
});
