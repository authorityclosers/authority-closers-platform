import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  loadLearnerInsightsData,
  LearnerInsightsPanel,
} from "../components/learner-insights";
import { LearnerShell } from "../components/site-shell";
import {
  createLearnerApi,
  type AnalyticsViewResponse,
  type LearnerApi,
} from "./learner-api";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const availableAnalytics: AnalyticsViewResponse = {
  status: "available",
  source: "descriptive_analytics_projection",
  period: "week",
  freshness_as_of: "2026-09-03T09:00:00Z",
  retained_event_count: 4,
  insights: [
    {
      id: "descriptive:planning-interaction",
      kind: "descriptive_signal",
      title: "Planning activity is present",
      detail: "A consented planning interaction was observed.",
      observed_event_count: 4,
      source_event_names: ["analytics.progress_viewed"],
    },
  ],
  disclaimer:
    "Descriptive product analytics only; never canonical progress, mastery, payment, entitlement, or access state.",
};

describe("learner descriptive insights", () => {
  it("keeps navigation support and notifications without a floating placeholder chatbot", () => {
    const html = renderToStaticMarkup(
      createElement(LearnerShell, { current: "progress" }),
    );

    expect(html).not.toContain('aria-label="Open help chatbox"');
    expect(html).not.toContain('aria-controls="learner-help-chatbox"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-label="Notifications"');
    expect(html).not.toContain("learner-help-chatbox__trigger");
    expect(html).toContain("mailto:");
    expect(html).toContain('aria-controls="learner-account-menu"');
  });

  it("presents analytics-only rhythm cues with source and state disclosures", () => {
    const html = renderToStaticMarkup(
      createElement(LearnerInsightsPanel, {
        state: { status: "ready", analytics: availableAnalytics },
        period: "week",
        onPeriodChange: vi.fn(),
        onRetry: vi.fn(),
      }),
    );

    expect(html).toContain("Learning rhythm");
    expect(html).toContain("Streak / rhythm");
    expect(html).toContain("Signal available");
    expect(html).toContain("Signals observed");
    expect(html).toContain("Source: descriptive analytics projection");
    expect(html).toContain("analytics.progress_viewed");
    expect(html).toContain("canonical progress");
    expect(html).not.toContain("aria-valuenow");
    expect(html).not.toContain("Mark all read");
  });

  it("keeps streak presentation explicitly insufficient when no signal exists", () => {
    const html = renderToStaticMarkup(
      createElement(LearnerInsightsPanel, {
        state: {
          status: "ready",
          analytics: {
            status: "insufficient_signal",
            source: "descriptive_analytics_projection",
            period: "week",
            freshness_as_of: null,
            retained_event_count: 0,
            insights: [],
            disclaimer:
              "Descriptive product analytics only; never canonical progress, mastery, payment, entitlement, or access state.",
          },
        },
        period: "week",
        onPeriodChange: vi.fn(),
        onRetry: vi.fn(),
      }),
    );

    expect(html).toContain("No signal yet");
    expect(html).toContain("No descriptive activity signals are available");
    expect(html).toContain("consented activity signals");
    expect(html).toContain('aria-pressed="true"');
    expect(html).not.toContain(">0<");
  });

  it("treats a missing insights method as an honest no-signal state", async () => {
    const result = await loadLearnerInsightsData({} as LearnerApi, "week");

    expect(result).toMatchObject({
      status: "ready",
      analytics: {
        status: "insufficient_signal",
        retained_event_count: 0,
        period: "week",
      },
    });
  });

  it("reads the bounded analytics endpoint without introducing a mutation", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(input).toBe("/v1/learning/insights?period=week");
        expect(init?.method).toBeUndefined();
        expect(init?.cache).toBe("no-store");
        expect(init?.credentials).toBe("include");
        return response(availableAnalytics);
      },
    );
    const api = createLearnerApi(fetcher);

    await expect(loadLearnerInsightsData(api, "week")).resolves.toMatchObject({
      status: "ready",
      analytics: availableAnalytics,
    });
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("falls back to insufficient signal when a deployment has not promoted the route", async () => {
    const api = createLearnerApi(
      vi.fn(async () => response({ title: "not promoted" }, 404)),
    );

    await expect(loadLearnerInsightsData(api, "month")).resolves.toMatchObject({
      analytics: {
        status: "insufficient_signal",
        period: "month",
        retained_event_count: 0,
      },
    });
  });
});
