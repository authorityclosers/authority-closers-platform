import { ROUTES } from "./routes";
import type { CourseIntent } from "./course-intent";
import {
  activityIntentHref,
  activityReturnHref,
  parseActivityIntent,
  type ActivityIntent,
} from "./activity-intent";
import { parseCourseIntent } from "./course-intent";
import {
  parseSalesAuthNext,
  salesAuthNextHref,
  SALES_XRAY_PATH,
  type SalesAuthNext,
} from "./sales-auth-return";
import type { QueryValue } from "./surface-state";

export type OnboardingReturnIntent = "home" | "settings";

export function parseOnboardingReturnIntent(
  value: QueryValue,
): OnboardingReturnIntent {
  const candidate = Array.isArray(value) ? value[0] : value;
  return candidate === "settings" ? "settings" : "home";
}

export function onboardingReturnHref(
  intent: OnboardingReturnIntent,
  courseIntent: CourseIntent = null,
  activityIntent: ActivityIntent = null,
  salesNext: SalesAuthNext = null,
): string {
  if (intent === "settings") return ROUTES.settings;
  if (parseCourseIntent(courseIntent) || parseActivityIntent(activityIntent)) {
    return activityReturnHref(activityIntent, courseIntent);
  }
  return parseSalesAuthNext(salesNext) ? SALES_XRAY_PATH : ROUTES.learnerHome;
}

export function onboardingHref(
  intent: OnboardingReturnIntent,
  courseIntent: CourseIntent = null,
  activityIntent: ActivityIntent = null,
  salesNext: SalesAuthNext = null,
): string {
  return intent === "settings"
    ? `${ROUTES.onboarding}?return=settings`
    : salesAuthNextHref(
        activityIntentHref(ROUTES.onboarding, activityIntent, courseIntent),
        courseIntent || activityIntent ? null : salesNext,
      );
}
