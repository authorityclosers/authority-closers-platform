import { LearnerHomeRuntime } from "../components/learner-runtime";
import { LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import { parseSurfaceState, type QueryValue } from "../lib/surface-state";

type LearnerHomePageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function LearnerHomePage({
  searchParams,
}: LearnerHomePageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="home">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container home-page">
          <SurfaceStatePanel
            state={state}
            retryHref={ROUTES.learnerHome}
            backHref={ROUTES.home}
          />
          {state === "DEFAULT" ? <LearnerHomeRuntime /> : null}
        </div>
      </main>
    </LearnerShell>
  );
}
