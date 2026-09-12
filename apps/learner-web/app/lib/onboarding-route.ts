import { ROUTES } from "./routes";
import { courseIntentHref, type CourseIntent } from "./course-intent";
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
): string {
  return intent === "settings"
    ? ROUTES.settings
    : courseIntentHref(ROUTES.learnerHome, courseIntent);
}

export function onboardingHref(
  intent: OnboardingReturnIntent,
  courseIntent: CourseIntent = null,
): string {
  return intent === "settings"
    ? `${ROUTES.onboarding}?return=settings`
    : courseIntentHref(ROUTES.onboarding, courseIntent);
}
