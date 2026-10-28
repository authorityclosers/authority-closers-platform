import { ScreenTitle } from "../../../../../shell/screen-title";
import { LiveModule } from "../../../../../components/learner-runtime";
import { SurfaceStatePanel } from "../../../../../components/surface-state";
import {
  parseSurfaceState,
  type QueryValue,
} from "../../../../../lib/surface-state";

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
    <>
      <ScreenTitle title="Module" />
      <main id="main-content" className="learner-main" tabIndex={-1}>
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
    </>
  );
}

export const metadata = { title: "Module" };
