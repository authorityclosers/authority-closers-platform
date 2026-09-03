import { NotificationsRuntime } from "../components/notifications-runtime";
import { NotificationsSkeleton } from "../components/skeletons";
import { LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import { parseSurfaceState, type QueryValue } from "../lib/surface-state";

type NotificationsPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function NotificationsPage({
  searchParams,
}: NotificationsPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="notifications">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container notifications-page">
          {state === "LOADING" ? (
            <NotificationsSkeleton />
          ) : (
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.notifications}
              backHref={ROUTES.dashboard}
            />
          )}
          {state === "DEFAULT" ? <NotificationsRuntime /> : null}
        </div>
      </main>
    </LearnerShell>
  );
}
