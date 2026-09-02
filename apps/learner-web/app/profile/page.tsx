import { ProfileRuntime } from "../components/profile-runtime";
import { ProfileSkeleton } from "../components/skeletons";
import { LearnerShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import { parseSurfaceState, type QueryValue } from "../lib/surface-state";

type ProfilePageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ProfilePage({ searchParams }: ProfilePageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="profile">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container profile-page">
          {state === "LOADING" ? (
            <ProfileSkeleton />
          ) : (
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.profile}
              backHref={ROUTES.dashboard}
            />
          )}
          {state === "DEFAULT" ? <ProfileRuntime /> : null}
        </div>
      </main>
    </LearnerShell>
  );
}
