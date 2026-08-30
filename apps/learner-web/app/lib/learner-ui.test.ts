import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import ActivityPage from "../activity/[activityId]/page";
import CallbackPage from "../auth/callback/page";
import CertificatePage from "../certificates/[certificateId]/page";
import { ActivityRenderer } from "../components/activity-renderers";
import { CoursePath } from "../components/course-path";
import { LoginForm } from "../components/login-form";
import { OnboardingForm } from "../components/onboarding-form";
import { ActivityStatusPill, ProgressMeter } from "../components/shared-ui";
import { Breadcrumbs } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import LearnerHomePage from "../home/page";
import ProgramLearningPage from "../learn/[programSlug]/page";
import CompletionPage from "../learn/[programSlug]/complete/page";
import ModulePage from "../learn/[programSlug]/module/[moduleId]/page";
import LoginPage from "../login/page";
import OnboardingPage from "../onboarding/page";
import PublicHomePage from "../page";
import ProgramDetailPage from "../programs/[slug]/page";
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
    "fails closed for direct locked activity URL %s regardless of query state",
    async (activityId) => {
      const page = await ActivityPage({
        params: Promise.resolve({ activityId }),
        searchParams: Promise.resolve({ state: "success-feedback" }),
      });
      const html = renderToStaticMarkup(page);

      expect(html).toContain('data-state="LOCKED"');
      expect(html).toContain("Complete the previous step first");
      expect(html).not.toContain("Success feedback");
      expect(html).not.toContain("Your turn.");
      expect(html).not.toContain("<form");
      expect(html).not.toContain("<textarea");
    },
  );

  it("fails closed for a direct locked module URL regardless of query state", async () => {
    const page = await ModulePage({
      params: Promise.resolve({
        programSlug: "free-course",
        moduleId: "module-02",
      }),
      searchParams: Promise.resolve({ state: "partial" }),
    });
    const html = renderToStaticMarkup(page);

    expect(html).toContain('data-state="LOCKED"');
    expect(html).not.toContain("Some information is unavailable");
    expect(html).not.toContain("Module sequence");
    expect(html).not.toContain("Open first activity");
  });

  it("does not link an available activity or course path directly into locked work", async () => {
    const activityPage = await ActivityPage({
      params: Promise.resolve({ activityId: "implement" }),
      searchParams: Promise.resolve({}),
    });
    const activityHtml = renderToStaticMarkup(activityPage);
    const pathHtml = renderToStaticMarkup(
      createElement(CoursePath, {
        programSlug: freeCourse.slug,
        modules: freeCourse.modules,
      }),
    );

    expect(activityHtml).toContain("Next activity locked");
    expect(activityHtml).not.toContain('href="/activity/review"');
    expect(pathHtml).not.toContain('href="/activity/review"');
    expect(pathHtml).not.toContain('href="/activity/improve"');
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

  it("keeps login and onboarding mutations visibly unavailable", () => {
    const login = renderToStaticMarkup(createElement(LoginForm));
    const onboarding = renderToStaticMarkup(createElement(OnboardingForm));

    expect(login).toContain("Email sign-in unavailable in preview");
    expect(login).toContain('disabled=""');
    expect(login).not.toContain("Continue with email");
    expect(onboarding).toContain("Profile setup unavailable in preview");
    expect(onboarding).toContain('disabled=""');
    expect(onboarding).not.toMatch(
      /Set up the preview|Continue to the preview home|context selected/,
    );
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

  it("keeps the home preview CTA and zero-evidence progress copy explicit", async () => {
    const html = renderToStaticMarkup(
      await LearnerHomePage({ searchParams: Promise.resolve({}) }),
    );

    expect(html).toContain("Open reflect preview");
    expect(html).toContain('aria-valuenow="0"');
    expect(html).toContain("0 / 5 · preview only");
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
    expect(html).toContain('<h2 id="certificate-title">');
  });
});
