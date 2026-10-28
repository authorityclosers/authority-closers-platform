import { ScreenTitle } from "../../shell/screen-title";
import { DiscoverRuntime } from "../../components/discover-runtime";
import { DiscoverSkeleton } from "../../components/skeletons";
import { SurfaceStatePanel } from "../../components/surface-state";
import { isStagingPublicCatalogPreview } from "../../lib/dev-api-proxy";
import { ROUTES } from "../../lib/routes";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

type DiscoverPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function DiscoverPage({
  searchParams,
}: DiscoverPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);
  const publicCatalogPreview = isStagingPublicCatalogPreview(
    process.env,
    process.env.NODE_ENV,
  );

  return (
    <>
      <ScreenTitle title="Discover" />
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container discover-page">
          {state === "LOADING" ? (
            <DiscoverSkeleton />
          ) : (
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.discover}
              backHref={ROUTES.dashboard}
            />
          )}
          {state === "DEFAULT" ? (
            <DiscoverRuntime publicCatalogPreview={publicCatalogPreview} />
          ) : null}
        </div>
      </main>
    </>
  );
}

export const metadata = { title: "Discover" };
