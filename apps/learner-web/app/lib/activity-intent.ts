import { courseIntentHref, type CourseIntent } from "./course-intent";
import { ROUTES } from "./routes";

export type ActivityIntent = string | null;

type ActivityIntentRoute =
  | typeof ROUTES.login
  | typeof ROUTES.register
  | typeof ROUTES.sessionExpired
  | typeof ROUTES.onboarding;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Navigation context only; the server owns access, enrollment and progress. */
export function parseActivityIntent(value: unknown): ActivityIntent {
  return typeof value === "string" &&
    value.length === 36 &&
    UUID_PATTERN.test(value)
    ? value.toLowerCase()
    : null;
}

export function activityIntentHref(
  route: ActivityIntentRoute,
  activityIntent: ActivityIntent = null,
  courseIntent: CourseIntent = null,
): string {
  const href = courseIntentHref(route, courseIntent);
  const activity = parseActivityIntent(activityIntent);
  if (!activity) return href;
  const separator = href.includes("?") ? "&" : "?";
  return `${href}${separator}${new URLSearchParams({ activity })}`;
}

export function activityReturnHref(
  activityIntent: ActivityIntent = null,
  courseIntent: CourseIntent = null,
): string {
  const activity = parseActivityIntent(activityIntent);
  return activity
    ? ROUTES.activity(activity)
    : courseIntentHref(ROUTES.learnerHome, courseIntent);
}
