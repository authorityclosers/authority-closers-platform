import { ScreenTitle } from "../../../../shell/screen-title";
import { LiveCompletionGate } from "../../../../components/learner-runtime";
import { SurfaceStatePanel } from "../../../../components/surface-state";
import {
  parseSurfaceState,
  type QueryValue,
} from "../../../../lib/surface-state";

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
    <>
      <ScreenTitle title="Course complete" />
      <main id="main-content" className="learner-main" tabIndex={-1}>
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
    </>
  );
}

export const metadata = { title: "Course complete" };
