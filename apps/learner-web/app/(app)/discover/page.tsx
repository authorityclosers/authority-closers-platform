import { ScreenTitle } from "../../shell/screen-title";
import { LearnScreen } from "../../reflex/learn";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

// Old catalogue links open Reflex Learn with Explore selected (28 Oct 2026).
export default async function DiscoverPage({
  searchParams,
}: {
  searchParams: Promise<{ state?: QueryValue }>;
}) {
  const query = await searchParams;
  return (
    <>
      <ScreenTitle title="Learn" />
      <LearnScreen state={parseSurfaceState(query.state)} view="explore" />
    </>
  );
}
export const metadata = { title: "Learn" };
