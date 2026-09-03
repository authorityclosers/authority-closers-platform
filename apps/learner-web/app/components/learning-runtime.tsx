"use client";

import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  LockKeyhole,
  RotateCcw,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ProgramCard, ProgressMeter, RouteHeader, StatusBanner } from "@ac/ui";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type LearnerApi,
  type LearningCollectionResponse,
  type LearningCourseSummaryResponse,
  type LearningResponse,
  type MeResponse,
} from "../lib/learner-api";
import {
  getEarliestOfflineReadMetadata,
  offlineReadNotice,
  type OfflineReadMetadata,
} from "../lib/offline-read-cache";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";
import {
  hasMembershipRole,
  MembershipUnavailable,
} from "./membership-availability";
import { useInvalidateDraftsWithoutMembership } from "./learner-runtime";
import { LearningSkeleton } from "./skeletons";

const defaultApi = createLearnerApi();

// Backwards-compatible export for older test fixtures. The learner library
// itself never uses a slug to select or authorize a course.
export { FREE_COURSE_SLUG } from "./learner-runtime";

type LearningFilter = "all" | "in_progress" | "completed" | "saved";

const FILTERS: Array<{ id: LearningFilter; label: string }> = [
  { id: "all", label: "All courses" },
  { id: "in_progress", label: "In progress" },
  { id: "completed", label: "Completed" },
  { id: "saved", label: "Saved" },
];

export function isActivityActionable(
  activity: LearningResponse["modules"][number]["activities"][number],
): boolean {
  const state = activity.state.toLowerCase();
  return (
    (state === "in_progress" || state === "available") &&
    activity.allowed_actions.length > 0
  );
}

/** Load the canonical learner-owned/enrolled course projection. */
export async function loadLearningData(
  api: LearnerApi,
  signal?: AbortSignal,
): Promise<{
  me: MeResponse;
  courses: LearningCourseSummaryResponse[];
  savedFilterAvailable: boolean;
  offlineRead?: OfflineReadMetadata;
}> {
  const me = await api.me({ signal });
  if (!hasMembershipRole(me)) {
    return {
      me,
      courses: [],
      savedFilterAvailable: false,
      offlineRead: getEarliestOfflineReadMetadata(me) ?? undefined,
    };
  }

  const courses: LearningCourseSummaryResponse[] = [];
  let nextCursor: string | undefined;
  let savedFilterAvailable = false;
  for (let page = 0; ; page += 1) {
    if (page >= 1000) {
      throw new Error("The learning collection returned too many pages.");
    }
    const collection: LearningCollectionResponse = await api.learningCollection(
      50,
      { signal, cursor: nextCursor },
    );
    courses.push(...collection.items);
    savedFilterAvailable ||= collection.saved_filter_available;
    const cursor = collection.next_cursor ?? undefined;
    if (!cursor) break;
    if (cursor === nextCursor) {
      throw new Error("The learning collection returned a repeated cursor.");
    }
    nextCursor = cursor;
  }
  return {
    me,
    courses,
    savedFilterAvailable,
    offlineRead:
      getEarliestOfflineReadMetadata(me, courses) ?? undefined,
  };
}

function formatEnrolledDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Enrollment date unavailable";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function stateLabel(state: LearningCourseSummaryResponse["state"]): string {
  if (state === "in_progress") return "In progress";
  if (state === "completed") return "Completed";
  return "Progress unavailable";
}

function stateClass(state: LearningCourseSummaryResponse["state"]): string {
  return `learning-course-card--${state.replaceAll("_", "-")}`;
}

function courseProjection(
  course: LearningCourseSummaryResponse,
): { value: number | null; detail: string } {
  const projection = course.projection;
  if (
    projection === null ||
    projection.denominator <= 0 ||
    !Number.isFinite(projection.percentage)
  ) {
    return {
      value: null,
      detail: "Progress is unavailable for this published course version.",
    };
  }
  const percentage = Math.round(
    Math.min(1, Math.max(0, projection.percentage)) * 100,
  );
  return {
    value: percentage,
    detail: `${projection.completed_count} of ${projection.denominator} required activities`,
  };
}

function LearningCourseCard({
  course,
  index,
}: {
  course: LearningCourseSummaryResponse;
  index: number;
}) {
  const progress = courseProjection(course);
  const titleId = `learning-course-${course.program_id}-${course.program_version_id}`;
  const href = ROUTES.programLearning(course.program_slug);

  return (
    <ProgramCard
      className={`learning-course-card ${stateClass(course.state)}`}
      title={course.program_title}
      titleId={titleId}
      titleAs="h2"
      eyebrow={`Course ${String(index + 1).padStart(2, "0")}`}
      badges={
        <span
          className={`learning-course-state learning-course-state--${course.state.replaceAll("_", "-")}`}
          data-course-state={course.state}
        >
          {course.state === "completed" ? (
            <CheckCircle2 size={14} aria-hidden="true" />
          ) : course.state === "unavailable" ? (
            <LockKeyhole size={14} aria-hidden="true" />
          ) : null}
          {stateLabel(course.state)}
        </span>
      }
      media={
        <div className="learning-course-card__media-content">
          <div className="learning-course-card__media-icon" aria-hidden="true">
            <BookOpen size={26} />
          </div>
          <div>
            <span className="learning-course-card__media-kicker">
              Authority Closers learning
            </span>
            <strong>Published version {course.version_number}</strong>
          </div>
        </div>
      }
      description="Follow the published course path and continue from the next server-authorized activity."
      meta={
        <span>
          Version {course.version_number} · Enrolled {formatEnrolledDate(course.enrolled_at)}
        </span>
      }
      action={
        <Link
          className="button button--cobalt learning-course-card__action-link"
          href={href}
          aria-label={`Open course outline for ${course.program_title}`}
          data-course-href={href}
        >
          Open course <ArrowRight size={16} aria-hidden="true" />
        </Link>
      }
    >
      <ProgressMeter
        value={progress.value}
        label="Course progress"
        detail={progress.detail}
      />
    </ProgramCard>
  );
}

function EmptyLearningState({
  filter,
  onClearFilter,
}: {
  filter: LearningFilter;
  onClearFilter: () => void;
}) {
  const filtered = filter !== "all";
  return (
    <section
      id="learning-course-list"
      className="card learning-collection-empty"
      aria-labelledby="learning-empty-title"
    >
      <div className="learning-collection-empty__icon" aria-hidden="true">
        <BookOpen size={26} />
      </div>
      <h2 id="learning-empty-title">
        {filtered
          ? "No courses match this view"
          : "No active course enrollments yet"}
      </h2>
      <p>
        {filtered
          ? "Only server-authorized course states appear in each view. Return to all courses to see the full library."
          : "Browse the published catalog to find a course available for this learner workspace."}
      </p>
      <div className="learning-collection-empty__actions">
        {filtered ? (
          <button
            className="button button--outline"
            type="button"
            onClick={onClearFilter}
          >
            View all courses
          </button>
        ) : null}
        <Link className="button button--cobalt" href={ROUTES.discover}>
          Browse Discover <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}

export function LearningViewRuntime({
  api = defaultApi,
}: {
  api?: LearnerApi;
}) {
  const [courses, setCourses] = useState<LearningCourseSummaryResponse[]>([]);
  const [savedFilterAvailable, setSavedFilterAvailable] = useState(false);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [offlineRead, setOfflineRead] = useState<OfflineReadMetadata | undefined>();
  const [filter, setFilter] = useState<LearningFilter>("all");
  const generationRef = useRef(0);
  const mountedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const membershipKnown = me !== null;
  const membershipAvailable = me !== null && hasMembershipRole(me);
  const draftCleanup = useInvalidateDraftsWithoutMembership(
    membershipKnown,
    membershipAvailable,
    me?.person_id ?? null,
  );

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const generation = ++generationRef.current;
    const isCurrent = () =>
      mountedRef.current &&
      generationRef.current === generation &&
      !controller.signal.aborted;

    setLoading(true);
    setError(null);
    setCourses([]);
    setSavedFilterAvailable(false);
    setOfflineRead(undefined);
    try {
      const result = await loadLearningData(api, controller.signal);
      if (!isCurrent()) return;
      setMe(result.me);
      setCourses(result.courses);
      setSavedFilterAvailable(result.savedFilterAvailable);
      setOfflineRead(result.offlineRead);
    } catch (err) {
      if (isAbortError(err) || !isCurrent()) return;
      setError(err);
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    mountedRef.current = true;
    void Promise.resolve().then(() => {
      if (mountedRef.current) void load();
    });
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      abortRef.current?.abort();
    };
  }, [load]);

  const visibleCourses = useMemo(() => {
    if (filter === "all") return courses;
    if (filter === "saved") {
      return savedFilterAvailable
        ? courses.filter((course) => course.saved_state === "saved")
        : [];
    }
    return courses.filter((course) => course.state === filter);
  }, [courses, filter, savedFilterAvailable]);

  if (loading) return <LearningSkeleton />;

  if (error) {
    const is401 = error instanceof ApiError && error.status === 401;
    const is403 = error instanceof ApiError && error.status === 403;
    return (
      <div className="surface-state surface-state--error-terminal" role="alert">
        <h1>
          {is401
            ? "Sign in to view your learning"
            : is403
              ? "Learner access is unavailable"
              : "Could not load your courses"}
        </h1>
        <p>
          {is401
            ? "Your session has expired. Sign in again to view your courses."
            : is403
              ? "This account is not authorized to view this learner library."
              : userFacingRequestError(
                  error,
                  "The learning service could not be reached. Try again.",
                )}
        </p>
        {is401 ? (
          <Link className="button button--ink" href={ROUTES.sessionExpired}>
            Sign in again
          </Link>
        ) : (
          <button
            className="button button--outline"
            type="button"
            onClick={() => void load()}
          >
            <RotateCcw size={16} aria-hidden="true" /> Retry
          </button>
        )}
      </div>
    );
  }

  if (!me || !hasMembershipRole(me)) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }

  return (
    <div
      className="learning-collection-view"
      data-testid="learning-collection"
    >
      <RouteHeader
        className="learning-collection-header"
        title="My Learning"
        titleId="learning-collection-title"
        eyebrow={
          <span className="card-badge card-badge--primary">Learner library</span>
        }
        description="Your server-authorized courses, organized around the published paths you can access."
        aside={
          <div
            className="learning-collection-summary"
            aria-label="Course library summary"
          >
            <strong>{courses.length}</strong>
            <span>
              {courses.length === 1 ? "enrolled course" : "enrolled courses"}
            </span>
          </div>
        }
      />

      {offlineRead ? (
        <div
          className="offline-read-notice"
          id="learning-offline-read"
          role="status"
        >
          {offlineReadNotice(offlineRead)}
        </div>
      ) : null}

      {!savedFilterAvailable ? (
        <StatusBanner state="info" title="Saved courses are not available yet.">
          This library does not have a canonical course bookmark projection.
          Activity drafts are kept separate and are not treated as saved
          courses.
        </StatusBanner>
      ) : null}

      <div className="learning-collection-toolbar">
        <div
          className="learning-collection-tabs"
          role="tablist"
          aria-label="Filter courses"
        >
          {FILTERS.map((item) => {
            const disabled = item.id === "saved" && !savedFilterAvailable;
            const selected = filter === item.id;
            return (
              <button
                key={item.id}
                id={`learning-filter-${item.id}`}
                className={`learning-collection-tab${selected ? " is-active" : ""}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls="learning-course-list"
                aria-disabled={disabled}
                disabled={disabled}
                onClick={() => setFilter(item.id)}
              >
                {item.label}
                {item.id === "saved" && !savedFilterAvailable
                  ? " · unavailable"
                  : null}
              </button>
            );
          })}
        </div>
        <span className="learning-collection-count" aria-live="polite">
          {visibleCourses.length} shown
        </span>
      </div>

      {visibleCourses.length > 0 ? (
        <section
          id="learning-course-list"
          className="learning-course-list"
          aria-label="Courses"
        >
          {visibleCourses.map((course, index) => (
            <LearningCourseCard
              key={`${course.program_id}:${course.program_version_id}`}
              course={course}
              index={index}
            />
          ))}
        </section>
      ) : (
        <EmptyLearningState
          filter={filter}
          onClearFilter={() => setFilter("all")}
        />
      )}
    </div>
  );
}
