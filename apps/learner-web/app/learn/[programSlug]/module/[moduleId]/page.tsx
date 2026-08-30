import { LiveModule } from "../../../../components/learner-runtime";
import { LearnerShell } from "../../../../components/site-shell";
import { SurfaceStatePanel } from "../../../../components/surface-state";
import {
  parseSurfaceState,
  type QueryValue,
} from "../../../../lib/surface-state";

type ModulePageProps = {
  params: Promise<{ programSlug: string; moduleId: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ModulePage({
  params,
  searchParams,
}: ModulePageProps) {
  const { programSlug, moduleId } = await params;
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="course">
      <main id="main-content" className="learner-main">
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={`/learn/${programSlug}/module/${moduleId}`}
            backHref={`/learn/${programSlug}`}
          />
          {state === "DEFAULT" ? (
            <LiveModule slug={programSlug} moduleId={moduleId} />
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
