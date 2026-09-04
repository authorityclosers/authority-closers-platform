import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ConnectedActivityWorkspace,
  FREE_COURSE_SLUG,
  HomeLearningPath,
  isForbiddenError,
  isSessionExpiredError,
  LearnerHomeEnrollmentCard,
  LearnerHomeOnboardingRedirect,
  learningPathStatusForError,
  LearningActivityNavigation,
} from "../components/learner-runtime";
import { isOnboardingSessionExpired } from "../components/onboarding-form";
import { LearnerShell } from "../components/site-shell";
import {
  ApiError,
  type ActivityResponse,
  type LearningActivityResponse,
  type LearningResponse,
  type ProgramSummaryResponse,
} from "./learner-api";

const activity: LearningActivityResponse = {
  id: "reflection-1",
  module_id: "module-1",
  program_version_id: "version-1",
  position: 2,
  kind: "REFLECTION",
  title: "Reflect on the signal",
  prompt: "What might your prospect be protecting?",
  state: "available",
  revision: 1,
  required: true,
  explanation: {
    activity_id: "reflection-1",
    state: "available",
    required: true,
    reason: "server_resolved_activity_state",
    missing_activity_ids: [],
    missing_module_ids: [],
  },
  allowed_actions: ["save_draft", "submit_evidence"],
};

const response: ActivityResponse = {
  ...activity,
  program_id: "program-1",
  enrollment_id: "enrollment-1",
  draft_revision: 0,
  draft_payload: null,
};

const learningLoop: LearningResponse = {
  program_id: "program-1",
  program_version_id: "version-1",
  program_slug: FREE_COURSE_SLUG,
  program_title: "Authority Closers Free Course",
  version_number: 1,
  enrollment_id: "enrollment-1",
  modules: [
    {
      id: "module-1",
      position: 1,
      title: "Why high-ticket sales is a different game",
      activities: [
        {
          ...activity,
          id: "watch-1",
          position: 1,
          kind: "VIDEO",
          title: "Watch the Module 1 shift",
          state: "completed",
          allowed_actions: [],
        },
        response,
        ...["IMPLEMENTATION_CHALLENGE", "REVIEW", "IMPROVE"].map(
          (kind, index) => ({
            ...activity,
            id: `locked-${index + 3}`,
            position: index + 3,
            kind,
            title: `Locked ${kind.toLowerCase()}`,
            state: "locked",
            allowed_actions: [] as [],
            explanation: {
              ...activity.explanation,
              activity_id: `locked-${index + 3}`,
              state: "locked",
              missing_activity_ids: ["reflection-1"],
              missing_module_ids: ["module-prerequisite"],
            },
          }),
        ),
      ],
    },
  ],
  projection: {
    scope_type: "course",
    scope_id: "program-1",
    program_version: "1",
    projection_version: "1",
    denominator: 5,
    completed_count: 1,
    percentage: 0.2,
    predicate: "required activities completed",
    missing_module_ids: ["module-1"],
    activity_reasons: [],
  },
};

const publishedFreeCourse: ProgramSummaryResponse = {
  id: "program-1",
  slug: "authority-closers-free-course",
  title: "Authority Closers Free Course",
  program_version_id: "version-1",
  version_number: 1,
  published_at: "2026-08-31T00:00:00Z",
};

describe("learner Clarity Grid slice", () => {
  it("renders only working learner navigation", () => {
    const html = renderToStaticMarkup(
      createElement(LearnerShell, { current: "dashboard" }, "content"),
    );

    expect(html).toContain('aria-label="Learner workspace navigation"');
    expect(html).toContain('aria-label="Learner mobile navigation"');
    expect(html).toContain('href="/learning"');
    expect(html).toContain('href="/discover"');
    expect(html).toContain('href="/progress"');
    expect(html).toContain('href="/notifications"');
    expect(html).toContain('href="/profile"');
    expect(html).toContain('href="/settings"');
    expect(html).not.toContain('aria-disabled="true"');
    expect(html).not.toContain("Search is coming later");
    expect(html).not.toContain("Certificate");
  });

  it("keeps fixed mobile navigation after the main content in DOM order", () => {
    const html = renderToStaticMarkup(
      createElement(
        LearnerShell,
        { current: "dashboard" },
        createElement("main", { id: "shell-content" }, "content"),
      ),
    );

    const contentIndex = html.indexOf('<main id="shell-content">');
    const navigationIndex = html.indexOf('<nav class="learner-bottom-nav"');

    expect(contentIndex).toBeGreaterThanOrEqual(0);
    expect(navigationIndex).toBeGreaterThan(contentIndex);
  });

  it("keeps Learning valid while incomplete onboarding redirects", () => {
    const redirect = renderToStaticMarkup(
      createElement(LearnerHomeOnboardingRedirect),
    );
    const onboardingShell = renderToStaticMarkup(
      createElement(
        LearnerShell,
        { current: "none", learningHref: "/onboarding" },
        "content",
      ),
    );

    expect(redirect).toContain('id="my-learning"');
    expect(redirect).toContain('role="status"');
    expect(onboardingShell).toContain('href="/onboarding"');
    expect(onboardingShell).not.toContain('href="/learning"');
  });

  it("offers the real published Free Course when there is no enrollment", () => {
    const html = renderToStaticMarkup(
      createElement(LearnerHomeEnrollmentCard, {
        learning: undefined,
        program: publishedFreeCourse,
      }),
    );

    expect(html).toContain('class="current-course-card"');
    expect(html).toContain("Free course");
    expect(html).toContain("Authority Closers Free Course");
    expect(html).toContain("Start free course");
    expect(html).toContain('href="/programs/authority-closers-free-course"');
    expect(html).not.toMatch(/projection unavailable|assignment collection/i);
  });

  it("keeps public program details preview-only and enrollment inside Home", () => {
    const source = readFileSync(
      new URL("../components/learner-runtime.tsx", import.meta.url),
      "utf8",
    );
    const publicDetail = source.slice(
      source.indexOf("export function PublicProgramDetail"),
      source.indexOf("export async function identityState"),
    );

    expect(publicDetail).toContain("Sign in to start free");
    expect(publicDetail).toContain("Create learner account");
    expect(publicDetail).not.toContain("api.enrollFree");
    expect(publicDetail).not.toContain("Enroll free");
  });

  it("renders the public program detail storefront with two-column hero and syllabus cards", () => {
    const source = readFileSync(
      new URL("../components/learner-runtime.tsx", import.meta.url),
      "utf8",
    );
    const publicDetail = source.slice(
      source.indexOf("export function PublicProgramDetail"),
      source.indexOf("export async function identityState"),
    );

    // Hero artwork & two-column layout
    expect(publicDetail).toContain("/media/ac-course-hero-v1.png");
    expect(publicDetail).toContain("program-hero");
    expect(publicDetail).toContain("program-hero__main");
    expect(publicDetail).toContain("program-hero__aside");
    expect(publicDetail).toContain("program-hero__preview-card");

    // Structured syllabus
    expect(publicDetail).toContain("program-curriculum-section");
    expect(publicDetail).toContain("public-module-detail-card");
    expect(publicDetail).toContain("public-activity-row");
    expect(publicDetail).toContain("Published Syllabus");

    // Clear CTAs
    expect(publicDetail).toContain("Sign in to start free");
    expect(publicDetail).toContain("Create learner account");

    // Negative assertions: no invented data or mutations
    expect(publicDetail).not.toContain("api.enrollFree");
    expect(publicDetail).not.toContain("Enroll free");
    expect(publicDetail).not.toContain("Structured Self-Paced");
    expect(publicDetail).not.toContain("Instant access upon sign-in");
    expect(publicDetail).not.toContain("Master high-impact closing frameworks");
    expect(publicDetail).not.toContain("Lessons");
    expect(publicDetail).toContain(
      "Published curriculum from the canonical catalog.",
    );
    expect(publicDetail).not.toMatch(/rating|stars|hours|reviews|instructor/i);
  });

  it("keeps locked modules non-navigable and review-pending modules available", () => {
    const learning: LearningResponse = {
      program_id: "program-1",
      program_version_id: "version-1",
      program_slug: FREE_COURSE_SLUG,
      program_title: "Authority Closers Free Course",
      version_number: 1,
      enrollment_id: "enrollment-1",
      modules: [
        {
          id: "module-locked",
          position: 1,
          title: "Locked module",
          activities: [
            {
              ...activity,
              id: "locked-activity",
              module_id: "module-locked",
              state: "locked",
              allowed_actions: [],
            },
          ],
        },
        {
          id: "module-review",
          position: 2,
          title: "Review module",
          activities: [
            {
              ...activity,
              id: "review-activity",
              module_id: "module-review",
              state: "awaiting_review",
              allowed_actions: [],
            },
          ],
        },
      ],
      projection: {
        scope_type: "course",
        scope_id: "program-1",
        program_version: "1",
        projection_version: "1",
        denominator: 2,
        completed_count: 0,
        percentage: 0,
        predicate: "required activities completed",
        missing_module_ids: ["module-locked", "module-review"],
        activity_reasons: [],
      },
    };
    const html = renderToStaticMarkup(
      createElement(HomeLearningPath, { learning }),
    );

    expect(html).toContain('aria-disabled="true"');
    expect(html).not.toContain(
      'href="/learn/authority-closers-free-course/module/module-locked"',
    );
    expect(html).toContain(
      'href="/learn/authority-closers-free-course/module/module-review"',
    );
    expect(html).toContain("Awaiting review");
  });

  it("renders server activity metadata and leaves locked activity non-navigable", () => {
    const available = renderToStaticMarkup(
      createElement(LearningActivityNavigation, { activity }),
    );
    const locked = renderToStaticMarkup(
      createElement(LearningActivityNavigation, {
        activity: { ...activity, state: "locked", allowed_actions: [] },
      }),
    );

    expect(available).toContain("Reflect on the signal");
    expect(available).toContain("REFLECTION");
    expect(available).toContain('href="/activity/reflection-1"');
    expect(locked).toContain('aria-disabled="true"');
    expect(locked).not.toContain("href=");
  });

  it("uses the Clarity response form without inventing reviewer feedback", () => {
    const html = renderToStaticMarkup(
      createElement(ConnectedActivityWorkspace, {
        activity: response,
        learning: learningLoop,
        learningPathStatus: "ready",
      }),
    );

    expect(html).toContain("Authority Closers Free Course");
    expect(html).toContain("Module 1");
    expect(html).toContain("2 of 5");
    expect(html).toContain('class="activity-response-form"');
    expect(html).toContain("Save reflection");
    expect(html).toContain("Submit evidence");
    expect(html).toContain("Reflection only — not an evaluation.");
    expect(html).toContain(
      "Complete 1 earlier required activity and 1 prerequisite module to unlock.",
    );
    expect(html).not.toContain("AI score");
    expect(html).not.toContain("reviewer feedback");
  });

  it("renders dependent-path session recovery without hiding the activity", () => {
    const html = renderToStaticMarkup(
      createElement(ConnectedActivityWorkspace, {
        activity: response,
        learningPathStatus: "error",
        learningPathError: new ApiError(401, "expired"),
      }),
    );

    expect(html).toContain(
      "Your session expired while refreshing the module path.",
    );
    expect(html).toContain("Sign in again");
    expect(html).toContain(response.title);
  });

  it("renders access recovery instead of a futile retry for a forbidden path", () => {
    const html = renderToStaticMarkup(
      createElement(ConnectedActivityWorkspace, {
        activity: response,
        learning: learningLoop,
        learningPathStatus: "forbidden",
        learningPathError: new ApiError(403, "denied"),
        onRetryLearningPath: () => undefined,
      }),
    );

    expect(html).toContain("Contact learner support");
    expect(html).toContain("mailto:admin@authorityclosers.com");
    expect(html).not.toContain("Retry module path");
    expect(html).not.toContain("Watch the Module 1 shift");
    expect(html).toContain(response.title);
  });

  it("recognizes only a 401 as session-expired mutation recovery", () => {
    expect(isSessionExpiredError(new ApiError(401, "expired"))).toBe(true);
    expect(isOnboardingSessionExpired(new ApiError(401, "expired"))).toBe(true);
    expect(isSessionExpiredError(new ApiError(403, "denied"))).toBe(false);
    expect(isOnboardingSessionExpired(new ApiError(403, "denied"))).toBe(false);
    expect(isSessionExpiredError(new TypeError("offline"))).toBe(false);
  });

  it("classifies dependent learning-path failures by recovery boundary", () => {
    expect(isForbiddenError(new ApiError(403, "denied"))).toBe(true);
    expect(isForbiddenError(new ApiError(401, "expired"))).toBe(false);
    expect(learningPathStatusForError(new ApiError(404, "missing"))).toBe(
      "unavailable",
    );
    expect(learningPathStatusForError(new ApiError(403, "denied"))).toBe(
      "forbidden",
    );
    expect(learningPathStatusForError(new ApiError(401, "expired"))).toBe(
      "error",
    );
    expect(learningPathStatusForError(new TypeError("offline"))).toBe("error");
  });

  it("reloads route identity and prevents stale path refresh overwrites", () => {
    const source = readFileSync(
      new URL("../components/learner-runtime.tsx", import.meta.url),
      "utf8",
    );
    const liveActivity = source.slice(
      source.indexOf("export function LiveActivity"),
      source.indexOf("export function LiveCertificate"),
    );

    expect(liveActivity).toContain("activityId,\n  );");
    expect(liveActivity).toContain("key={state.value.activity.id}");
    expect(source).toContain("const refresh = onMutationCommitted?.(kind);");
    expect(source).toContain('if (kind === "draft") return;');
    expect(source).toContain("++learningPathGeneration.current");
    expect(source).toContain(
      "if (generation !== learningPathGeneration.current) return;",
    );
    expect(source).not.toContain("await onMutationCommitted?.();");
  });

  it("keeps skip-link targets programmatically focusable", () => {
    const activityPage = readFileSync(
      new URL("../activity/[activityId]/page.tsx", import.meta.url),
      "utf8",
    );

    expect(activityPage).toContain('id="main-content"');
    expect(activityPage).toContain("tabIndex={-1}");
  });

  it("collapses task flows for mobile and keeps safe-area and touch-target contracts", () => {
    const authStyles = readFileSync(
      new URL("../auth-clarity.css", import.meta.url),
      "utf8",
    );
    const onboardingStyles = readFileSync(
      new URL("../onboarding-clarity.css", import.meta.url),
      "utf8",
    );
    const learnerStyles = readFileSync(
      new URL("../learner-clarity.css", import.meta.url),
      "utf8",
    );
    const themeStyles = readFileSync(
      new URL("../theme.css", import.meta.url),
      "utf8",
    );

    expect(authStyles).toContain("@media (max-width: 760px)");
    expect(authStyles).toContain(".clarity-auth-masthead");
    expect(authStyles).toMatch(
      /\.clarity-auth-workspace \{[^}]*grid-template-columns: 1fr;/s,
    );
    expect(authStyles).toContain("env(safe-area-inset-bottom)");
    expect(authStyles).toMatch(
      /\.clarity-auth-card \.button \{[^}]*min-height: 52px;/s,
    );
    expect(onboardingStyles).toContain("@media (max-width: 760px)");
    expect(learnerStyles).toMatch(
      /\.site-frame--learner \.button \{[^}]*min-height: 44px;/s,
    );
    expect(learnerStyles).toMatch(
      /\.activity-shell__breadcrumb > a \{[^}]*min-height: 44px;/s,
    );
    expect(learnerStyles).toMatch(
      /\.activity-response-form__heading \{[^}]*display: flex;/s,
    );
    expect(themeStyles).toContain(
      'html[data-theme="dark"] .site-frame--learner .activity-stage-summary',
    );
    expect(themeStyles).toContain(
      'html[data-theme="dark"] .site-frame--learner .activity-mobile-path',
    );
    expect(themeStyles).toMatch(
      /html\[data-theme="dark"\][\s\S]*\.learner-bottom-nav[\s\S]*color: var\(--theme-text-muted\);/,
    );
    expect(learnerStyles).toContain(".activity-mobile-path__summary-meta svg");
  });

  it("keeps the profile surface on theme tokens in both appearance modes", () => {
    const learnerStyles = readFileSync(
      new URL("../learner-clarity.css", import.meta.url),
      "utf8",
    );
    const themeStyles = readFileSync(
      new URL("../theme.css", import.meta.url),
      "utf8",
    );
    const profileStart = learnerStyles.indexOf("Profile View Styles");
    const profileEnd = learnerStyles.indexOf("Notifications View Styles");
    const profileStyles = learnerStyles.slice(profileStart, profileEnd);

    expect(profileStyles).toContain(
      "--color-card-surface: var(--theme-surface);",
    );
    expect(profileStyles).toContain("color: var(--theme-text);");
    expect(profileStyles).not.toMatch(
      /#(?:0f172a|64748b|ffffff|f1f5f9|eff6ff|2563eb|f8fafc)/i,
    );
    expect(themeStyles).toContain('html[data-theme="dark"] {');
    expect(themeStyles).toContain("--theme-surface: #101a2b;");
    expect(themeStyles).toContain("--theme-text: #edf2fb;");
    expect(themeStyles).toContain("--theme-border: #34425a;");
  });
});
