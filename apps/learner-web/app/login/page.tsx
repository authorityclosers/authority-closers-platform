import { AuthFlowPage } from "../components/auth-flow-page";
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
    <AuthFlowPage
      eyebrow="Account access"
      heading="Sign in to your account."
      copy="Sign in to continue your Authority Closers learning."
      backHref={ROUTES.home}
      backLabel="Back to the public catalog"
      steps={[
        { label: "Sign in", state: "current" },
        { label: "Verify", state: "upcoming" },
        { label: "Start learning", state: "upcoming" },
      ]}
    >
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
          pageHeadingPresent
        />
      ) : null}
      {isContentVisible(state) ? (
        <LoginForm
          stagingBridge={stagingBridge}
          courseIntent={courseIntent}
          activityIntent={activityIntent}
          salesNext={salesNext}
        />
      ) : null}
    </AuthFlowPage>
  );
}
