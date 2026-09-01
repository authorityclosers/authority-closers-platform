import { PublicProgramDetail } from "../../components/learner-runtime";
import { PublicShell } from "../../components/site-shell";
import { SurfaceStatePanel } from "../../components/surface-state";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

type ProgramDetailPageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ProgramDetailPage({
  params,
  searchParams,
}: ProgramDetailPageProps) {
  const { slug } = await params;
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <PublicShell current="program">
      <main id="main-content" className="public-main" tabIndex={-1}>
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            backHref="/"
            retryHref={`/programs/${slug}`}
          />
          {state === "DEFAULT" ? <PublicProgramDetail slug={slug} /> : null}
        </div>
      </main>
    </PublicShell>
  );
}
