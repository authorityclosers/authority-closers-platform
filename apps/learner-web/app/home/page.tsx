import { DashboardRuntime } from "../components/dashboard-runtime";
import { DashboardSkeleton } from "../components/skeletons";
import { LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import { courseIntentHref, parseCourseIntent } from "../lib/course-intent";
import { parseSurfaceState, type QueryValue } from "../lib/surface-state";

type LearnerHomePageProps = {
  searchParams: Promise<{ state?: QueryValue; course?: QueryValue }>;
};

export default async function LearnerHomePage({
  searchParams,
}: LearnerHomePageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);
  const courseIntent = parseCourseIntent(query.course);

  return (
    <LearnerShell current="dashboard">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container home-page">
          {state === "LOADING" ? (
            <DashboardSkeleton />
          ) : (
            <SurfaceStatePanel
              state={state}
              retryHref={courseIntentHref(ROUTES.learnerHome, courseIntent)}
              signInHref={courseIntentHref(ROUTES.login, courseIntent)}
              backHref={ROUTES.home}
            />
          )}
          {state === "DEFAULT" ? (
            <DashboardRuntime courseIntent={courseIntent} />
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
