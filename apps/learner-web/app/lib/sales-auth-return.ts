import { parseActivityIntent, activityIntentHref } from "./activity-intent";
import { parseCourseIntent } from "./course-intent";
import type { ActivityIntent } from "./activity-intent";
import type { CourseIntent } from "./course-intent";
import { ROUTES } from "./routes";

/** The only Sales continuation the learner surface may carry. */
export const SALES_XRAY_PATH = "/sales-xray" as const;
export type SalesAuthNext = typeof SALES_XRAY_PATH | null;

export function parseSalesAuthNext(value: unknown): SalesAuthNext {
  return value === SALES_XRAY_PATH ? SALES_XRAY_PATH : null;
}

export function salesAuthNextHref(
  path: string,
  next: SalesAuthNext = null,
): string {
  const validated = parseSalesAuthNext(next);
  if (!validated) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}${new URLSearchParams({ next: validated })}`;
}

/** Existing learner intent wins over the bounded Sales continuation. */
export function preferredSalesAuthNext(
  courseIntent: CourseIntent = null,
  activityIntent: ActivityIntent = null,
  next: unknown = null,
): SalesAuthNext {
  return parseCourseIntent(courseIntent) || parseActivityIntent(activityIntent)
    ? null
    : parseSalesAuthNext(next);
}

type AuthIntentRoute = Parameters<typeof activityIntentHref>[0];

export function authIntentHref(
  route: AuthIntentRoute,
  activityIntent: ActivityIntent = null,
  courseIntent: CourseIntent = null,
  next: SalesAuthNext = null,
): string {
  const base = activityIntentHref(route, activityIntent, courseIntent);
  return salesAuthNextHref(
    base,
    preferredSalesAuthNext(courseIntent, activityIntent, next),
  );
}

/** Signed provider return paths use this exact unencoded internal value. */
export function salesAuthReturnPath(next: SalesAuthNext = null): string | null {
  return parseSalesAuthNext(next)
    ? `${ROUTES.onboarding}?next=${SALES_XRAY_PATH}`
    : null;
}
