import { ROUTES } from "./routes";

export const FREE_COURSE_SLUG = "authority-closers-free-course";
export type CourseIntent = typeof FREE_COURSE_SLUG | null;

/** Navigation context only. Membership and enrollment remain server-owned. */
export function parseCourseIntent(value: unknown): CourseIntent {
  return value === FREE_COURSE_SLUG ? FREE_COURSE_SLUG : null;
}

type CourseIntentRoute =
  | typeof ROUTES.login
  | typeof ROUTES.register
  | typeof ROUTES.learnerHome
  | typeof ROUTES.onboarding
  | typeof ROUTES.sessionExpired
  | typeof ROUTES.forgotPassword
  | typeof ROUTES.verifyEmail
  | typeof ROUTES.resetPassword;

export function courseIntentHref(
  route: CourseIntentRoute,
  intent: CourseIntent = null,
): string {
  const course = parseCourseIntent(intent);
  return course ? `${route}?${new URLSearchParams({ course })}` : route;
}
