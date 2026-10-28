import {
  createLearnerApi,
  type LearnerApi,
  type LearningCourseSummaryResponse,
  type LearningResponse,
} from "../lib/learner-api";

export const learnerApi = createLearnerApi();
export type Course = {
  summary: LearningCourseSummaryResponse;
  learning: LearningResponse | null;
};

/** Read all pages so the most recently updated enrolment is not missed. */
async function readLibrary(api: LearnerApi, signal: AbortSignal) {
  const items: LearningCourseSummaryResponse[] = [];
  const seen = new Set<string>();
  let cursor: string | undefined;
  do {
    const page = await api.learningCollection(50, { signal, cursor });
    items.push(...page.items);
    cursor = page.next_cursor ?? undefined;
    if (cursor && seen.has(cursor))
      throw new Error("Course list did not finish loading");
    if (cursor) seen.add(cursor);
  } while (cursor);
  return items.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export async function readCourses(
  api: LearnerApi,
  signal: AbortSignal,
): Promise<Course[]> {
  const items = await readLibrary(api, signal);
  return Promise.all(
    items.map(async (summary) => ({
      summary,
      learning:
        summary.state === "unavailable"
          ? null
          : await api.learning(
              summary.program_id,
              {
                enrollmentId: summary.enrollment_id,
                programVersionId: summary.program_version_id,
              },
              { signal },
            ),
    })),
  );
}

export async function readCourse(
  api: LearnerApi,
  slug: string,
  signal: AbortSignal,
) {
  // Enrolled identity/version comes from the private library, including courses
  // whose public catalogue entry has since been superseded.
  const course = (await readLibrary(api, signal)).find(
    (item) => item.program_slug === slug,
  );
  if (!course || course.state === "unavailable")
    throw new Error("Course unavailable");
  return api.learning(
    course.program_id,
    {
      enrollmentId: course.enrollment_id,
      programVersionId: course.program_version_id,
    },
    { signal },
  );
}

export const percent = (fraction: number) =>
  Math.round(Math.max(0, Math.min(1, fraction)) * 100);
const activityKinds: Record<string, string> = {
  VIDEO: "Watch",
  REFLECTION: "Reflect",
  IMPLEMENTATION_CHALLENGE: "Implement",
  REVIEW: "Review",
  IMPROVE: "Improve",
};
const learningStates: Record<string, string> = {
  completed: "Done",
  available: "Available",
  in_progress: "In progress",
  awaiting_review: "Waiting for review",
  locked: "Locked",
};
export const kindLabel = (kind: string) =>
  activityKinds[kind.toUpperCase()] ?? "Step";
export const stateLabel = (state: string) =>
  learningStates[state.toLowerCase()] ?? "Unavailable";
export const courseHref = (slug: string) =>
  `/learn/${encodeURIComponent(slug)}`;
export const practiceHref = (id: string, attempt?: string) =>
  `/practice?set=${encodeURIComponent(id)}${attempt ? `&attempt=${encodeURIComponent(attempt)}` : ""}`;
