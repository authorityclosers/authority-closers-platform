import { ScreenTitle } from "../../shell/screen-title";
import { TodayScreen } from "../../reflex/today";
import { isPracticeUiEnabled } from "../../lib/practice-availability";
import { parseCourseIntent } from "../../lib/course-intent";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

export default async function LearnerHomePage({
  searchParams,
}: {
  searchParams: Promise<{ state?: QueryValue; course?: QueryValue }>;
}) {
  const query = await searchParams;
  return (
    <>
      <ScreenTitle title="Today" />
      <TodayScreen
        state={parseSurfaceState(query.state)}
        courseIntent={parseCourseIntent(query.course)}
        practiceEnabled={isPracticeUiEnabled(process.env)}
      />
    </>
  );
}
export const metadata = { title: "Today" };
export const dynamic = "force-dynamic";
