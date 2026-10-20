import { notFound } from "next/navigation";

import { ProviderHub } from "../../sales-xray/provider-hub";
import { normalizeHub } from "../../sales-xray/provider-hub-data";
import { StageAssignments } from "../../sales-xray/stage-assignments";
import { Page, PageHeader } from "../../ui/kit";
import { hubFixture } from "./hub-fixture";
import {
  jobsAnswers,
  jobsMetrics,
  jobsPrices,
  jobsSettings,
} from "./jobs-fixture";

/**
 * Local review of the Providers hub with fictional catalogue data (no API, no key, no
 * account), for screenshots at phone and desktop widths. Never in a production build.
 */
export default async function ProvidersFixturePage({
  searchParams,
}: {
  searchParams: Promise<{ provider?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { provider } = await searchParams;
  return (
    <Page>
      <PageHeader
        title="Providers & costs"
        context={["Fixture: fictional catalogue data"]}
      />
      <StageAssignments
        metrics={jobsMetrics}
        settings={jobsSettings}
        answers={jobsAnswers}
        prices={jobsPrices}
      />
      <ProviderHub hub={normalizeHub(hubFixture(provider ?? null))} />
    </Page>
  );
}
