import { ScreenTitle } from "../../../../../shell/screen-title";
import { CourseScreen } from "../../../../../reflex/course";
import {
  parseSurfaceState,
  type QueryValue,
} from "../../../../../lib/surface-state";

export default async function ModulePage({
  params,
  searchParams,
}: {
  params: Promise<{ programSlug: string; moduleId: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
}) {
  const path = await params;
  const query = await searchParams;
  return (
    <>
      <ScreenTitle title="Module" />
      <CourseScreen
        slug={path.programSlug}
        moduleId={path.moduleId}
        state={parseSurfaceState(query.state)}
      />
    </>
  );
}
export const metadata = { title: "Module" };
