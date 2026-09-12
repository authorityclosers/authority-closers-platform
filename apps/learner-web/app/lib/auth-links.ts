import { courseIntentHref, type CourseIntent } from "./course-intent";
import { ROUTES } from "./routes";

type GoogleAuthAction = "authenticate" | "register";

export const GOOGLE_REGISTRATION_RETURN_PATH = "/onboarding";

export function googleAuthReturnPath(
  action: GoogleAuthAction,
  courseIntent: CourseIntent = null,
): string {
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
): string {
  const parameters = new URLSearchParams({
    action,
    surface: "learner",
    return_path: googleAuthReturnPath(action, courseIntent),
  });
  return `/v1/auth/google/start?${parameters.toString()}`;
}
