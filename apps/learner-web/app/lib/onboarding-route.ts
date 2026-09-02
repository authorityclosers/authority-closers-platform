import { ROUTES } from "./routes";
import type { QueryValue } from "./surface-state";

export type OnboardingReturnIntent = "home" | "settings";

export function parseOnboardingReturnIntent(
  value: QueryValue,
): OnboardingReturnIntent {
  const candidate = Array.isArray(value) ? value[0] : value;
  return candidate === "settings" ? "settings" : "home";
}

export function onboardingReturnHref(intent: OnboardingReturnIntent): string {
  return intent === "settings" ? ROUTES.settings : ROUTES.learnerHome;
}

export function onboardingHref(intent: OnboardingReturnIntent): string {
  return intent === "settings"
    ? `${ROUTES.onboarding}?return=settings`
    : ROUTES.onboarding;
}
