import {
  courseIntentHref,
  parseCourseIntent,
  type CourseIntent,
} from "./course-intent";
import {
  activityIntentHref,
  parseActivityIntent,
  type ActivityIntent,
} from "./activity-intent";
import { ROUTES } from "./routes";
import {
  parseSalesAuthNext,
  salesAuthReturnPath,
  type SalesAuthNext,
} from "./sales-auth-return";

type GoogleAuthAction = "authenticate" | "register";

export const GOOGLE_REGISTRATION_RETURN_PATH = "/onboarding";

export function googleAuthReturnPath(
  action: GoogleAuthAction,
  courseIntent: CourseIntent = null,
  activityIntent: ActivityIntent = null,
  salesNext: SalesAuthNext = null,
): string {
  // Onboarding reads canonical status before returning to a protected activity.
  if (parseActivityIntent(activityIntent)) {
    return activityIntentHref(ROUTES.onboarding, activityIntent, courseIntent);
  }
  const coursePath = courseIntentHref(
    action === "register"
      ? GOOGLE_REGISTRATION_RETURN_PATH
      : ROUTES.learnerHome,
    courseIntent,
  );
  return parseCourseIntent(courseIntent)
    ? coursePath
    : parseSalesAuthNext(salesNext)
      ? (salesAuthReturnPath(salesNext) ?? coursePath)
      : coursePath;
}

export function googleAuthStartUrl(
  action: GoogleAuthAction,
  courseIntent: CourseIntent = null,
  activityIntent: ActivityIntent = null,
  salesNext: SalesAuthNext = null,
): string {
  const parameters = new URLSearchParams({
    action,
    surface: "learner",
    return_path: googleAuthReturnPath(
      action,
      courseIntent,
      activityIntent,
      salesNext,
    ),
  });
  return `/v1/auth/google/start?${parameters.toString()}`;
}
