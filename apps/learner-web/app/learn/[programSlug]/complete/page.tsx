import { LiveCompletionGate } from "../../../components/learner-runtime";
import { LearnerShell } from "../../../components/site-shell";
import { SurfaceStatePanel } from "../../../components/surface-state";
import { parseSurfaceState, type QueryValue } from "../../../lib/surface-state";

type CompletionPageProps = {
  params: Promise<{ programSlug: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function CompletionPage({
  params,
  searchParams,
}: CompletionPageProps) {
  const { programSlug } = await params;
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="course">
      <main id="main-content" className="learner-main">
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={`/learn/${programSlug}/complete`}
            backHref={`/learn/${programSlug}`}
          />
          {state === "DEFAULT" ? (
            <LiveCompletionGate slug={programSlug} />
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
