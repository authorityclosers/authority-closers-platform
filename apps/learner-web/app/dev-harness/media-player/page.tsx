import { notFound } from "next/navigation";

import { MediaPlayerStressHarness } from "../../components/media-player-stress-harness";

type MediaPlayerStressHarnessPageProps = {
  searchParams: Promise<{
    fixture?: string;
    scenario?: string;
  }>;
};

/**
 * Development-only browser harness. It deliberately never participates in
 * the learner route or the server-owned learning API.
 */
export default async function MediaPlayerStressHarnessPage({
  searchParams,
}: MediaPlayerStressHarnessPageProps) {
  if (process.env.NODE_ENV === "production") notFound();
  const params = await searchParams;
  return (
    <MediaPlayerStressHarness
      initialFixture={params.fixture}
      initialScenario={params.scenario}
    />
  );
}
