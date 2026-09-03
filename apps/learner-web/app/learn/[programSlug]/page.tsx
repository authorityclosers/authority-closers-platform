import { LiveLearningPath } from "../../components/learner-runtime";
import { LearnerShell } from "../../components/site-shell";
import { SurfaceStatePanel } from "../../components/surface-state";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

type ProgramLearningPageProps = {
  params: Promise<{ programSlug: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ProgramLearningPage({
  params,
  searchParams,
}: ProgramLearningPageProps) {
  const { programSlug } = await params;
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="course">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={`/learn/${programSlug}`}
            backHref="/home"
          />
          {state === "DEFAULT" ? <LiveLearningPath slug={programSlug} /> : null}
        </div>
      </main>
    </LearnerShell>
  );
}
