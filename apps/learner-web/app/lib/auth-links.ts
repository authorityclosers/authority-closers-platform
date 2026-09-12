import { courseIntentHref, type CourseIntent } from "./course-intent";
import {
  activityIntentHref,
  parseActivityIntent,
  type ActivityIntent,
} from "./activity-intent";
import { ROUTES } from "./routes";

type GoogleAuthAction = "authenticate" | "register";

export const GOOGLE_REGISTRATION_RETURN_PATH = "/onboarding";

export function googleAuthReturnPath(
  action: GoogleAuthAction,
  courseIntent: CourseIntent = null,
  activityIntent: ActivityIntent = null,
): string {
  // Onboarding reads canonical status before returning to a protected activity.
  if (parseActivityIntent(activityIntent)) {
    return activityIntentHref(ROUTES.onboarding, activityIntent, courseIntent);
  }
  return courseIntentHref(
    action === "register"
      ? GOOGLE_REGISTRATION_RETURN_PATH
      : ROUTES.learnerHome,
    courseIntent,
  );
}

export function googleAuthStartUrl(
  action: GoogleAuthAction,
  courseIntent: CourseIntent = null,
  activityIntent: ActivityIntent = null,
): string {
  const parameters = new URLSearchParams({
    action,
    surface: "learner",
    return_path: googleAuthReturnPath(action, courseIntent, activityIntent),
  });
  return `/v1/auth/google/start?${parameters.toString()}`;
}
