import { ScreenTitle } from "../../../shell/screen-title";
import { CourseScreen } from "../../../reflex/course";
import { parseSurfaceState, type QueryValue } from "../../../lib/surface-state";

export default async function ProgramLearningPage({
  params,
  searchParams,
}: {
  params: Promise<{ programSlug: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
}) {
  const path = await params;
  const query = await searchParams;
  return (
    <>
      <ScreenTitle title="Course" />
      <CourseScreen
        slug={path.programSlug}
        state={parseSurfaceState(query.state)}
      />
    </>
  );
}
export const metadata = { title: "Course" };
