import { PublicCatalogHome } from "./components/learner-runtime";
import { parseSurfaceState, type QueryValue } from "./lib/surface-state";
import { PublicShell } from "./components/site-shell";
import { SurfaceStatePanel } from "./components/surface-state";
import { ROUTES } from "./lib/routes";

type HomePageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <PublicShell>
      <main id="main-content" className="public-main">
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={ROUTES.home}
            backHref={ROUTES.home}
          />
          {state === "DEFAULT" ? <PublicCatalogHome /> : null}
        </div>
      </main>
    </PublicShell>
  );
}
