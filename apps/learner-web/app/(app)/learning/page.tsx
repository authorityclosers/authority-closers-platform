import { ScreenTitle } from "../../shell/screen-title";
import { LearnScreen } from "../../reflex/learn";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

export default async function LearningPage({
  searchParams,
}: {
  searchParams: Promise<{ state?: QueryValue; view?: QueryValue }>;
}) {
  const query = await searchParams;
  return (
    <>
      <ScreenTitle title="Learn" />
      <LearnScreen
        state={parseSurfaceState(query.state)}
        view={query.view === "explore" ? "explore" : "mine"}
      />
    </>
  );
}
export const metadata = { title: "Learn" };
