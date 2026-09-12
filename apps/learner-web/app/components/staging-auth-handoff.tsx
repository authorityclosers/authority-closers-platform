import { type CourseIntent } from "../lib/course-intent";
import {
  activityIntentHref,
  type ActivityIntent,
} from "../lib/activity-intent";

const STAGING_APP_ORIGIN = "https://staging.authorityclosers.com";

export function StagingAuthHandoff({
  path,
  action,
  courseIntent = null,
  activityIntent = null,
}: {
  path: "/register" | "/forgot-password" | "/verify-email" | "/reset-password";
  action: string;
  courseIntent?: CourseIntent;
  activityIntent?: ActivityIntent;
}) {
  const target =
    path === "/register"
      ? activityIntentHref(path, activityIntent, courseIntent)
      : path;
  const href = new URL(target, STAGING_APP_ORIGIN).toString();
  return (
    <div className="auth-card">
      <h2>Continue on deployed staging.</h2>
      <p className="auth-card__intro">
        {action} remains on the canonical staging origin so one-time links and
        provider callbacks are never relayed through localhost.
      </p>
      <a className="button button--ink button--full" href={href}>
        Open deployed staging
      </a>
    </div>
  );
}
