import { CalendarRuntime } from "../components/calendar-runtime";
import { CalendarSkeleton } from "../components/skeletons";
import { LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import { parseSurfaceState, type QueryValue } from "../lib/surface-state";

type CalendarPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function CalendarPage({
  searchParams,
}: CalendarPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="calendar">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container calendar-page">
          {state === "LOADING" ? (
            <CalendarSkeleton />
          ) : (
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.calendar}
              backHref={ROUTES.dashboard}
            />
          )}
          {state === "DEFAULT" ? <CalendarRuntime /> : null}
        </div>
      </main>
    </LearnerShell>
  );
}
