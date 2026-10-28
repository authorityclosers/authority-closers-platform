"use client";

import { Empty, Panel, Skeleton } from "@ac/ui/kit";
import { BookOpen } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { type LearnerApi } from "../lib/learner-api";
import {
  FREE_COURSE_SLUG,
  courseIntentHref,
  type CourseIntent,
} from "../lib/course-intent";
import { firstActionableActivity } from "../lib/next-learning-action";
import { isContentVisible, type SurfaceState } from "../lib/surface-state";
import {
  practiceEngineApi,
  type PracticeEngineApi,
} from "../lib/practice-engine-api";
import { useReflexAccount } from "../shell/account-store";
import {
  LearnerHomeEnrollmentCard,
  useInvalidateDraftsWithoutMembership,
} from "../components/learner-runtime";
import { hasMembershipRole } from "../components/membership-availability";
import { courseHref, kindLabel, learnerApi, readCourses } from "./data";
import {
  CourseRows,
  Failure,
  Progress,
  Screen,
  ScreenSkeleton,
  SimulatedState,
  WeekDots,
  styles,
  useRead,
} from "./shared";

function TodayPractice({ api }: { api: PracticeEngineApi }) {
  const read = useCallback(
    (signal: AbortSignal) => api.progress(signal),
    [api],
  );
  const result = useRead(read);
  return (
    <Panel title="Today’s practice">
      {result.loading ? (
        <div
          className={styles.week}
          role="status"
          aria-label="Loading your practice days"
        >
          <Skeleton height={83} />
        </div>
      ) : result.error ? (
        <Failure error={result.error} retry={result.retry} />
      ) : result.data ? (
        <WeekDots days={result.data.actual_practice_days_this_week} />
      ) : null}
      <Link className={styles.quietLink} href="/practice">
        Open practice
      </Link>
    </Panel>
  );
}

// The greeting's time of day: read once on the client (the server renders without it).
let pageTime: Date | null = null;
const subscribeClock = () => () => {};
const clientNow = () => (pageTime ??= new Date());
const serverNow = (): Date | null => null;

export function TodayScreen({
  api = learnerApi,
  practiceApi = practiceEngineApi,
  practiceEnabled = false,
  state = "DEFAULT",
  courseIntent = null,
}: {
  api?: LearnerApi;
  practiceApi?: PracticeEngineApi;
  practiceEnabled?: boolean;
  state?: SurfaceState;
  courseIntent?: CourseIntent;
}) {
  const account = useReflexAccount();
  const now = useSyncExternalStore(subscribeClock, clientNow, serverNow);
  const read = useCallback(
    async (signal: AbortSignal) => {
      const me = account.me ?? (await api.me({ signal }));
      if (!hasMembershipRole(me))
        return { me, courses: [], freeCourse: undefined, needsSetup: false };
      const setup = await api.onboarding({ signal });
      if (setup.status !== "completed" && setup.status !== "skipped")
        return { me, courses: [], freeCourse: undefined, needsSetup: true };
      const courses = await readCourses(api, signal);
      const programs = courses.length
        ? null
        : await api.listPrograms(50, { signal });
      return {
        me,
        courses,
        freeCourse: programs?.items.find(
          (program) => program.slug === FREE_COURSE_SLUG,
        ),
        needsSetup: false,
      };
    },
    [api, account.me],
  );
  const result = useRead(read, isContentVisible(state));
  const membership = Boolean(result.data && hasMembershipRole(result.data.me));
  useInvalidateDraftsWithoutMembership(
    Boolean(result.data),
    membership,
    result.data?.me.person_id ?? null,
  );
  useEffect(() => {
    if (result.data?.needsSetup)
      window.location.replace(courseIntentHref("/onboarding", courseIntent));
  }, [result.data?.needsSetup, courseIntent]);
  const hour = now?.getHours() ?? 9;
  const greeting =
    hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const firstName = result.data?.me.display_name?.trim().split(/\s+/)[0];
  const courses = result.data?.courses ?? [];
  const current = courses.find(
    (course) => course.summary.state === "in_progress" && course.learning,
  );
  const learning = current?.learning;
  const next = learning ? firstActionableActivity(learning) : undefined;

  return (
    <Screen state={state} retryHref={courseIntentHref("/home", courseIntent)}>
      {state === "LOADING" || (isContentVisible(state) && result.loading) ? (
        <ScreenSkeleton kind="today" practiceEnabled={practiceEnabled} />
      ) : !isContentVisible(state) ? (
        <SimulatedState
          state={state}
          retryHref={courseIntentHref("/home", courseIntent)}
          signInHref={courseIntentHref("/login", courseIntent)}
        />
      ) : result.error ? (
        <Failure error={result.error} retry={result.retry} />
      ) : result.data?.needsSetup ? (
        <Empty
          link={Link}
          icon={BookOpen}
          title="Let’s set up your learning."
          action={{
            href: courseIntentHref("/onboarding", courseIntent),
            label: "Continue setup",
          }}
        />
      ) : result.data && !membership ? (
        <Empty
          link={Link}
          icon={BookOpen}
          title="Open Reflex with your learner account."
          action={{
            href: courseIntentHref("/login", courseIntent),
            label: "Sign in",
          }}
        />
      ) : (
        <div className={styles.stack}>
          <header className={styles.greeting}>
            <h2>
              {greeting}
              {firstName ? `, ${firstName}` : ""}
            </h2>
            <time dateTime={now?.toLocaleDateString("en-CA")}>
              {now?.toLocaleDateString(undefined, {
                weekday: "long",
                day: "numeric",
                month: "long",
              })}
            </time>
          </header>
          {learning ? (
            <Panel title="Continue learning">
              <div className={`${styles.primaryBody} ${styles.continueBody}`}>
                <p>{learning.program_title}</p>
                <h3>{next?.title ?? "Your next step is on the way"}</h3>
                {next ? (
                  <span>{kindLabel(next.kind)}</span>
                ) : (
                  <p>Open your course to see what’s ready.</p>
                )}
                <Progress
                  value={learning.projection.percentage}
                  title={learning.program_title}
                />
                <Link
                  className={styles.primaryLink}
                  href={
                    next
                      ? `/activity/${encodeURIComponent(next.id)}`
                      : courseHref(learning.program_slug)
                  }
                >
                  Continue
                </Link>
              </div>
            </Panel>
          ) : courses.length ? (
            <Panel title="Keep learning">
              <Empty
                link={Link}
                icon={BookOpen}
                title="Your courses are ready to revisit."
                action={{ href: "/learning", label: "Open my courses" }}
              />
            </Panel>
          ) : (
            <Panel title="Start your first course">
              {result.data?.freeCourse ? (
                <div className={styles.enrollment}>
                  <p>Learn with Closers&apos; Academy.</p>
                  <LearnerHomeEnrollmentCard
                    api={api}
                    program={result.data.freeCourse}
                  />
                </div>
              ) : (
                <Empty
                  link={Link}
                  icon={BookOpen}
                  title="New courses are on the way."
                  action={{
                    href: "/learning?view=explore",
                    label: "Explore courses",
                  }}
                />
              )}
            </Panel>
          )}
          {practiceEnabled ? <TodayPractice api={practiceApi} /> : null}
          <Panel
            link={Link}
            title="Your courses"
            action={{ href: "/learning", label: "See all" }}
          >
            {courses.length ? (
              <CourseRows courses={courses.slice(0, 3)} />
            ) : (
              <Empty
                link={Link}
                icon={BookOpen}
                title="You haven’t started a course yet."
                action={{
                  href: "/learning?view=explore",
                  label: "Explore courses",
                }}
              />
            )}
          </Panel>
        </div>
      )}
    </Screen>
  );
}
