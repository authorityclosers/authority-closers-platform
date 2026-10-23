import { expect, it } from "vitest";

import {
  feedbackApiPath,
  feedbackFilters,
  feedbackQuery,
  goodShare,
  normalizeFeedback,
  worse,
} from "./feedback-data";

it("keeps only known filters, 30 days by default", () => {
  expect(feedbackFilters({})).toEqual({ days: 30 });
  expect(feedbackFilters({ days: "7", moment: "report_read" })).toEqual({
    days: 7,
    moment: "report_read",
  });
  expect(feedbackFilters({ days: "5", moment: "nowhere" })).toEqual({
    days: 30,
  });
  expect(feedbackQuery({ days: 90, moment: "app_update" })).toBe(
    "days=90&moment=app_update",
  );
  expect(feedbackQuery({ days: 30 })).toBe("");
  expect(feedbackApiPath({ days: 30 })).toBe("/v1/admin/feedback?days=30");
});

it("reads the summary, with defaults for anything odd", () => {
  const summary = normalizeFeedback({
    days: 7,
    moments: [
      {
        moment: "report_read",
        good: 3,
        okay: 1,
        bad: 0,
        dismissed: 2,
        opted_out: 1,
        comments: 1,
      },
    ],
    releases: [
      {
        release: "abcdef123456789",
        last_at: "2026-10-23T10:00:00+00:00",
        good: 1,
      },
    ],
    by_day: [{ day: "2026-10-23", good: 1, bad: 2 }],
    recent: [
      {
        feedback_id: "f1",
        moment: "call_outcome",
        rating: "bad",
        comment: "Lost my note",
        route: "/leads",
      },
      { feedback_id: "f2", moment: "general", rating: "weird" },
    ],
    week: { rated: 6, bad: 3, rated_before: 6, bad_before: 1 },
  });
  expect(summary.moments[0]).toMatchObject({
    moment: "report_read",
    good: 3,
    optedOut: 1,
  });
  expect(summary.releases[0]).toMatchObject({
    release: "abcdef123456789",
    okay: 0,
  });
  expect(summary.recent.map((row) => row.rating)).toEqual(["bad", null]);
  expect(goodShare(summary.moments[0])).toBe(75);
  expect(
    goodShare({
      good: 0,
      okay: 0,
      bad: 0,
      dismissed: 1,
      optedOut: 0,
      comments: 0,
    }),
  ).toBeNull();
  expect(worse(summary.week)).toBe(true);
  expect(worse({ rated: 4, bad: 2, ratedBefore: 4, badBefore: 1 })).toBe(false);
  expect(normalizeFeedback(null).moments).toEqual([]);
});
