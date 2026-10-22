import { notFound } from "next/navigation";

import { normalizeEngine } from "../../analysis-engine/engine-data";
import { EngineView } from "../../analysis-engine/engine-view";
import { Page, PageHeader } from "../../ui/kit";
import { engineFixture } from "./engine-fixture";

/**
 * Local review of the analysis engine page with fictional numbers (no API, no account):
 * live, an old export, and an environment with no export. Never in a production build.
 */
export default async function EngineFixturePage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { state } = await searchParams;
  const chosen = state === "stale" || state === "empty" ? state : "live";
  const engine = normalizeEngine(engineFixture(new Date(), chosen));
  return (
    <Page wide>
      <PageHeader
        title="Analysis engine"
        context={["Fixture: fictional numbers"]}
      />
      <EngineView engine={engine} />
    </Page>
  );
}
