import { ProgressRuntime } from "../components/progress-runtime";
import { ProgressSkeleton } from "../components/skeletons";
import { LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import { parseSurfaceState, type QueryValue } from "../lib/surface-state";

type ProgressPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ProgressPage({
  searchParams,
}: ProgressPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="progress">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container progress-page">
          {state === "LOADING" ? (
            <ProgressSkeleton />
          ) : (
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.progress}
              backHref={ROUTES.dashboard}
            />
          )}
          {state === "DEFAULT" ? <ProgressRuntime /> : null}
        </div>
      </main>
    </LearnerShell>
  );
}
