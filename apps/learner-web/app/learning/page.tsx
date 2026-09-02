import { LearningViewRuntime } from "../components/learning-runtime";
import { LearningSkeleton } from "../components/skeletons";
import { LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import { parseSurfaceState, type QueryValue } from "../lib/surface-state";

type LearningPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function LearningPage({
  searchParams,
}: LearningPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="learning">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container learning-page">
          {state === "LOADING" ? (
            <LearningSkeleton />
          ) : (
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.learning}
              backHref={ROUTES.dashboard}
            />
          )}
          {state === "DEFAULT" ? <LearningViewRuntime /> : null}
        </div>
      </main>
    </LearnerShell>
  );
}
