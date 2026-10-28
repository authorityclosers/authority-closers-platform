import { ScreenTitle } from "../../shell/screen-title";
import { LearningViewRuntime } from "../../components/learning-runtime";
import { LearningSkeleton } from "../../components/skeletons";
import { SurfaceStatePanel } from "../../components/surface-state";
import { ROUTES } from "../../lib/routes";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

type LearningPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function LearningPage({
  searchParams,
}: LearningPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <>
      <ScreenTitle title="Learn" />
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
    </>
  );
}

export const metadata = { title: "Learn" };
