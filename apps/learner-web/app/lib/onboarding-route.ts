import { ROUTES } from "./routes";
import type { CourseIntent } from "./course-intent";
import {
  activityIntentHref,
  activityReturnHref,
  type ActivityIntent,
} from "./activity-intent";
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
): string {
  return intent === "settings"
    ? ROUTES.settings
    : activityReturnHref(activityIntent, courseIntent);
}

export function onboardingHref(
  intent: OnboardingReturnIntent,
  courseIntent: CourseIntent = null,
  activityIntent: ActivityIntent = null,
): string {
  return intent === "settings"
    ? `${ROUTES.onboarding}?return=settings`
    : activityIntentHref(ROUTES.onboarding, activityIntent, courseIntent);
}
