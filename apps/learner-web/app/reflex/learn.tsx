"use client";

import { Empty, Panel, Segmented } from "@ac/ui/kit";
import { BookOpen } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { ApiError, type LearnerApi } from "../lib/learner-api";
import { isContentVisible, type SurfaceState } from "../lib/surface-state";
import { courseHref, learnerApi, readCourses } from "./data";
import {
  Artwork,
  CourseRows,
  Failure,
  Screen,
  ScreenSkeleton,
  SimulatedState,
  styles,
  useRead,
} from "./shared";

export function LearnScreen({
  api = learnerApi,
  view = "mine",
  state = "DEFAULT",
}: {
  api?: LearnerApi;
  view?: "mine" | "explore";
  state?: SurfaceState;
}) {
  const router = useRouter();
  const read = useCallback(
    async (signal: AbortSignal) => {
      if (view === "mine")
        return { courses: await readCourses(api, signal), programs: [] };
      const [catalog, courses] = await Promise.all([
        api.listPrograms(50, { signal }),
        readCourses(api, signal).catch((error) => {
          if (
            error instanceof ApiError &&
            (error.status === 401 || error.status === 403)
          )
            return [];
          throw error;
        }),
      ]);
      return { courses, programs: catalog.items };
    },
    [api, view],
  );
  const result = useRead(read, isContentVisible(state));
  return (
    <Screen
      state={state}
      retryHref={view === "explore" ? "/learning?view=explore" : "/learning"}
    >
      <div className={styles.stack}>
        <Segmented
          label="Courses"
          value={view}
          items={[
            { key: "mine", label: "My courses" },
            { key: "explore", label: "Explore" },
          ]}
          onChange={(next) =>
            router.replace(
              next === "explore" ? "/learning?view=explore" : "/learning",
              { scroll: false },
            )
          }
        />
        {state === "LOADING" || (isContentVisible(state) && result.loading) ? (
          <ScreenSkeleton kind={view === "explore" ? "explore" : "learn"} />
        ) : !isContentVisible(state) ? (
          <SimulatedState
            state={state}
            retryHref={
              view === "explore" ? "/learning?view=explore" : "/learning"
            }
          />
        ) : result.error ? (
          <Failure error={result.error} retry={result.retry} />
        ) : view === "mine" ? (
          <Panel title="My courses">
            {result.data?.courses.length ? (
              <CourseRows courses={result.data.courses} />
            ) : (
              <Empty
                link={Link}
                icon={BookOpen}
                title="You haven’t started a course yet"
                action={{ href: "/learning?view=explore", label: "Explore" }}
              />
            )}
          </Panel>
        ) : (
          <section className={styles.stack} aria-labelledby="explore-title">
            <h2 id="explore-title">Courses from Closers&apos; Academy</h2>
            {result.data?.programs.length ? (
              <div className={styles.grid}>
                {result.data.programs.map((program) => {
                  const enrolled = (result.data?.courses ?? []).some(
                    (course) => course.summary.program_id === program.id,
                  );
                  const moduleCount =
                    "modules" in program && Array.isArray(program.modules)
                      ? program.modules.length
                      : "module_count" in program &&
                          typeof program.module_count === "number"
                        ? program.module_count
                        : null;
                  return (
                    <Panel key={program.id} title={program.title}>
                      <div className={styles.primaryBody}>
                        <Artwork large />
                        {moduleCount !== null ? (
                          <p>
                            {moduleCount}{" "}
                            {moduleCount === 1 ? "module" : "modules"}
                          </p>
                        ) : null}
                        <Link
                          className={styles.quietLink}
                          href={
                            enrolled
                              ? courseHref(program.slug)
                              : `/programs/${encodeURIComponent(program.slug)}`
                          }
                        >
                          {enrolled ? "Continue" : "View course"}
                        </Link>
                      </div>
                    </Panel>
                  );
                })}
              </div>
            ) : (
              <Empty
                link={Link}
                icon={BookOpen}
                title="New courses are on the way."
                action={{ href: "/learning", label: "My courses" }}
              />
            )}
          </section>
        )}
      </div>
    </Screen>
  );
}
