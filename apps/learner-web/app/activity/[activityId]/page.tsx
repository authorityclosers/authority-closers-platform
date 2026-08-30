import { LiveActivity } from "../../components/learner-runtime";
import { LearnerShell } from "../../components/site-shell";
import { SurfaceStatePanel } from "../../components/surface-state";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

type ActivityPageProps = {
  params: Promise<{ activityId: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ActivityPage({
  params,
  searchParams,
}: ActivityPageProps) {
  const { activityId } = await params;
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="course">
      <main id="main-content" className="learner-main">
        <div className="page-container activity-page">
          <SurfaceStatePanel
            state={state}
            retryHref={`/activity/${activityId}`}
            backHref="/home"
          />
          {state === "DEFAULT" ? (
            <LiveActivity activityId={activityId} />
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
