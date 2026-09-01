import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ConnectedActivityWorkspace,
  isSessionExpiredError,
  LearnerHomeEnrollmentCard,
  LearningActivityNavigation,
} from "../components/learner-runtime";
import { isOnboardingSessionExpired } from "../components/onboarding-form";
import { LearnerShell } from "../components/site-shell";
import {
  ApiError,
  type ActivityResponse,
  type LearningActivityResponse,
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
  it("renders the supported shell with honest disabled extension navigation", () => {
    const html = renderToStaticMarkup(
      createElement(LearnerShell, { current: "home" }, "content"),
    );

    expect(html).toContain('aria-label="Learner workspace navigation"');
    expect(html).toContain('placeholder="Search is coming later"');
    expect(html).toContain('aria-label="Learner mobile navigation"');
    expect(html).toContain('aria-disabled="true"');
    expect(html).not.toContain("Certificate");
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

  it("collapses split flows before their minimum width and keeps touch targets at 44px", () => {
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

    expect(authStyles.match(/@media \(max-width: 960px\)/g)).toHaveLength(2);
    expect(authStyles).toContain(".clarity-auth-mobile-header");
    expect(authStyles).toMatch(
      /\.site-frame--auth \.clarity-auth-context \{[^}]*display: none;/s,
    );
    expect(authStyles).toContain("env(safe-area-inset-bottom)");
    expect(authStyles).toMatch(
      /\.site-frame--auth \.clarity-auth-card \.button--ink,[^{]+\{[^}]*min-height: 52px;/s,
    );
    expect(onboardingStyles).toContain("@media (max-width: 960px)");
    expect(learnerStyles).toMatch(
      /\.site-frame--learner \.button \{[^}]*min-height: 44px;/s,
    );
  });
});
