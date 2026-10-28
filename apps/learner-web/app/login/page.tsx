import styles from "../components/reflex-login.module.css";
import { handoffReturnPath } from "../lib/cross-app-handoff";
import { LoginForm } from "../components/login-form";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../lib/surface-state";
import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { parseCourseIntent } from "../lib/course-intent";
import { parseActivityIntent } from "../lib/activity-intent";
import { authIntentHref, parseSalesAuthNext } from "../lib/sales-auth-return";

type LoginPageProps = {
  searchParams: Promise<{
    state?: QueryValue;
    course?: QueryValue;
    activity?: QueryValue;
    next?: QueryValue;
    return?: QueryValue;
    handoff?: QueryValue;
  }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);
  const courseIntent = parseCourseIntent(query.course);
  const activityIntent = parseActivityIntent(query.activity);
  const salesNext = parseSalesAuthNext(query.next);
  const stagingBridge = isStagingAuthenticatedBridge(
    process.env,
    process.env.NODE_ENV,
  );

  return (
    <main className={styles.page} id="main-content">
      {state !== "DEFAULT" ? (
        <SurfaceStatePanel
          state={state}
          retryHref={authIntentHref(
            ROUTES.login,
            activityIntent,
            courseIntent,
            salesNext,
          )}
          signInHref={authIntentHref(
            ROUTES.login,
            activityIntent,
            courseIntent,
            salesNext,
          )}
          backHref={ROUTES.home}
          pageHeadingPresent={isContentVisible(state)}
        />
      ) : null}
      {isContentVisible(state) ? (
        <LoginForm
          stagingBridge={stagingBridge}
          handoffExpired={query.handoff === "expired"}
          returnPath={
            typeof (query.return ?? query.next) === "string"
              ? handoffReturnPath(query.return ?? query.next)
              : undefined
          }
          courseIntent={courseIntent}
          activityIntent={activityIntent}
          salesNext={salesNext}
        />
      ) : null}
    </main>
  );
}

export const metadata = { title: "Sign in" };
