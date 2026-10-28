import { ScreenTitle } from "../../../shell/screen-title";
import { LiveActivity } from "../../../components/learner-runtime";
import { SurfaceStatePanel } from "../../../components/surface-state";
import { parseSurfaceState, type QueryValue } from "../../../lib/surface-state";

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
    <>
      <ScreenTitle title="Lesson" />
      <main id="main-content" className="learner-main" tabIndex={-1}>
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
    </>
  );
}

export const metadata = { title: "Lesson" };
