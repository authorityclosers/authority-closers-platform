import { ScreenTitle } from "../../shell/screen-title";
import { ProfileRuntime } from "../../components/profile-runtime";
import { ProfileSkeleton } from "../../components/skeletons";
import { SurfaceStatePanel } from "../../components/surface-state";
import { ROUTES } from "../../lib/routes";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

type ProfilePageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ProfilePage({ searchParams }: ProfilePageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <>
      <ScreenTitle title="Me" />
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
    </>
  );
}

export const metadata = { title: "Me" };
