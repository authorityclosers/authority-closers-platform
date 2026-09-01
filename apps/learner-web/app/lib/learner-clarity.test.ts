import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ConnectedActivityWorkspace,
  FREE_COURSE_SLUG,
  HomeLearningPath,
  isSessionExpiredError,
  LearnerHomeEnrollmentCard,
  LearnerHomeOnboardingRedirect,
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
  enrollment_id: "enrollment-1",
  draft_revision: 0,
  draft_payload: null,
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
      createElement(LearnerShell, { current: "home" }, "content"),
    );

    expect(html).toContain('aria-label="Learner workspace navigation"');
    expect(html).toContain('aria-label="Learner mobile navigation"');
    expect(html).toContain('href="/home#my-learning"');
    expect(html).toContain('href="/progress"');
    expect(html).toContain('href="/settings"');
    expect(html).not.toContain('aria-disabled="true"');
    expect(html).not.toContain("Practice");
    expect(html).not.toContain("Library");
    expect(html).not.toContain("Search is coming later");
    expect(html).not.toContain("Certificate");
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
    expect(onboardingShell).not.toContain('href="/home#my-learning"');
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
      createElement(ConnectedActivityWorkspace, { activity: response }),
    );

    expect(html).toContain("My learning");
    expect(html).toContain("REFLECTION");
    expect(html).toContain('class="activity-response-form"');
    expect(html).toContain("Submit evidence");
    expect(html).not.toContain("AI score");
    expect(html).not.toContain("reviewer feedback");
  });

  it("recognizes only a 401 as session-expired mutation recovery", () => {
    expect(isSessionExpiredError(new ApiError(401, "expired"))).toBe(true);
    expect(isOnboardingSessionExpired(new ApiError(401, "expired"))).toBe(true);
    expect(isSessionExpiredError(new ApiError(403, "denied"))).toBe(false);
    expect(isOnboardingSessionExpired(new ApiError(403, "denied"))).toBe(false);
    expect(isSessionExpiredError(new TypeError("offline"))).toBe(false);
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
  });
});
