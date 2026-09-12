// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  activityIntentHref,
  activityReturnHref,
  parseActivityIntent,
} from "./activity-intent";
import { courseIntentHref, FREE_COURSE_SLUG } from "./course-intent";
import { ROUTES } from "./routes";

const activity = "a12b3c4d-5e6f-4781-92a3-b4c5d6e7f809";
const course = FREE_COURSE_SLUG;
const authRoutes = [
  ROUTES.login,
  ROUTES.sessionExpired,
  ROUTES.onboarding,
] as const;

describe("bounded activity navigation intent", () => {
  it.each([
    { name: "missing", value: undefined },
    { name: "null", value: null },
    { name: "empty", value: "" },
    { name: "boolean", value: true },
    { name: "number", value: 42 },
    { name: "empty array", value: [] },
    { name: "single UUID array", value: [activity] },
    { name: "duplicate UUID array", value: [activity, activity] },
    { name: "object", value: { activity } },
    { name: "missing hyphens", value: activity.replaceAll("-", "") },
    { name: "wrong separator", value: activity.replace("-", "_") },
    { name: "short UUID", value: activity.slice(0, -1) },
    { name: "long UUID", value: `${activity}0` },
    { name: "non-hex UUID", value: activity.replace("a", "g") },
    { name: "leading space", value: ` ${activity}` },
    { name: "trailing space", value: `${activity} ` },
    { name: "leading tab", value: `\t${activity}` },
    { name: "trailing newline", value: `${activity}\n` },
    { name: "trailing CRLF", value: `${activity}\r\n` },
    { name: "braced UUID", value: `{${activity}}` },
    { name: "UUID URN", value: `urn:uuid:${activity}` },
    { name: "activity path", value: `/activity/${activity}` },
    { name: "absolute URL", value: `https://external.test/${activity}` },
    { name: "protocol-relative URL", value: `//external.test/${activity}` },
    { name: "query", value: `${activity}?course=${course}` },
    { name: "fragment", value: `${activity}#draft` },
    { name: "slash", value: `${activity}/another` },
    { name: "backslash", value: `${activity}\\another` },
    { name: "encoded hex", value: `%61${activity.slice(1)}` },
    { name: "encoded hyphen", value: activity.replace("-", "%2D") },
  ])("rejects $name without coercion or trimming", ({ value }) => {
    expect(parseActivityIntent(value)).toBeNull();
  });

  it.each([activity, activity.toUpperCase(), activity.replace("a", "A")])(
    "normalizes canonical UUID hex %s",
    (value) => {
      expect(parseActivityIntent(value)).toBe(activity);
    },
  );

  it("accepts UUID hex without imposing version or variant policy", () => {
    const identifier = "01234567-89ab-cdef-0123-456789abcdef";
    expect(parseActivityIntent(identifier)).toBe(identifier);
  });

  it.each(authRoutes)(
    "keeps default and course-only %s bytes unchanged",
    (route) => {
      expect(activityIntentHref(route)).toBe(route);
      expect(activityIntentHref(route, null)).toBe(courseIntentHref(route));
      expect(activityIntentHref(route, undefined, course)).toBe(
        `${route}?course=${course}`,
      );
      expect(activityIntentHref(route, null, course)).toBe(
        courseIntentHref(route, course),
      );
    },
  );

  it.each(authRoutes)("adds one normalized activity hint to %s", (route) => {
    expect(activityIntentHref(route, activity.toUpperCase())).toBe(
      `${route}?activity=${activity}`,
    );
    const href = activityIntentHref(route, activity.toUpperCase(), course);
    expect(href).toBe(`${route}?course=${course}&activity=${activity}`);
    const url = new URL(href, "https://learner.example.test");
    expect(url.pathname).toBe(route);
    expect([...url.searchParams.entries()]).toEqual([
      ["course", course],
      ["activity", activity],
    ]);
    expect(url.hash).toBe("");
  });

  it.each([
    "//external.test",
    `/activity/${activity}`,
    `${activity}?next=https://external.test`,
    `${activity}#draft`,
    `${activity}\n`,
  ])("revalidates directly supplied strings in both builders: %j", (value) => {
    for (const route of authRoutes) {
      expect(activityIntentHref(route, value)).toBe(courseIntentHref(route));
      expect(activityIntentHref(route, value, course)).toBe(
        courseIntentHref(route, course),
      );
    }
    expect(activityReturnHref(value)).toBe(ROUTES.learnerHome);
    expect(activityReturnHref(value, course)).toBe(
      courseIntentHref(ROUTES.learnerHome, course),
    );
  });

  it("returns only the fixed activity path with no navigation hints", () => {
    expect(activityReturnHref(activity)).toBe(`/activity/${activity}`);
    expect(activityReturnHref(activity.toUpperCase(), course)).toBe(
      ROUTES.activity(activity),
    );
    const url = new URL(
      activityReturnHref(activity, course),
      "https://learner.example.test",
    );
    expect(url.pathname).toBe(`/activity/${activity}`);
    expect(url.search).toBe("");
    expect(url.hash).toBe("");
  });

  it("retains the existing home fallback without an activity", () => {
    expect(activityReturnHref()).toBe(ROUTES.learnerHome);
    expect(activityReturnHref(null)).toBe(courseIntentHref(ROUTES.learnerHome));
    expect(activityReturnHref(undefined, course)).toBe(
      `/home?course=${course}`,
    );
    expect(activityReturnHref(null, course)).toBe(
      courseIntentHref(ROUTES.learnerHome, course),
    );
  });
});
