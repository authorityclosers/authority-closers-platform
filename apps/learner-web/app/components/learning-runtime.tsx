"use client";

import { ArrowRight, BookOpen, RotateCcw } from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { RouteHeader, StatusBanner } from "@ac/ui";

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
import {
  LEARNER_SUPPORT_HREF,
  useInvalidateDraftsWithoutMembership,
} from "./learner-runtime";
import { LearningCourseCard } from "./learning-course-card";
import { LearningSkeleton } from "./skeletons";

const defaultApi = createLearnerApi();

// Backwards-compatible export for older test fixtures. The learner library
// itself never uses a slug to select or authorize a course.
export { FREE_COURSE_SLUG } from "./learner-runtime";

export type LearningFilter = "all" | "in_progress" | "completed" | "saved";

const FILTERS: Array<{ id: LearningFilter; label: string }> = [
  { id: "all", label: "All courses" },
  { id: "in_progress", label: "In progress" },
  { id: "completed", label: "Completed" },
  { id: "saved", label: "Saved" },
];

export function filterLearningCourses(
  courses: LearningCourseSummaryResponse[],
  filter: LearningFilter,
  savedFilterAvailable: boolean,
): LearningCourseSummaryResponse[] {
  if (filter === "all") return courses;
  if (filter === "saved") {
    return savedFilterAvailable
      ? courses.filter((course) => course.saved_state === "saved")
      : [];
  }
  return courses.filter((course) => course.state === filter);
}

/** Return the next enabled tab for the controlled course filter list. */
export function getLearningFilterKeyboardTarget(
  current: LearningFilter,
  key: string,
  savedFilterAvailable: boolean,
): LearningFilter | null {
  const enabled = FILTERS.filter(
    (item) => item.id !== "saved" || savedFilterAvailable,
  );
  const currentIndex = enabled.findIndex((item) => item.id === current);
  if (currentIndex === -1) return null;
  if (key === "Home") return enabled[0]?.id ?? null;
  if (key === "End") return enabled.at(-1)?.id ?? null;

  const direction =
    key === "ArrowRight" || key === "ArrowDown"
      ? 1
      : key === "ArrowLeft" || key === "ArrowUp"
        ? -1
        : 0;
  if (direction === 0) return null;
  return (
    enabled[(currentIndex + direction + enabled.length) % enabled.length]?.id ??
    null
  );
}

export type LearningLoadErrorClass = "retryable" | "terminal";

const RETRYABLE_LEARNING_STATUSES = new Set([408, 425, 429]);

export function getLearningLoadErrorClass(
  error: unknown,
): LearningLoadErrorClass {
  if (
    error instanceof ApiError &&
    (RETRYABLE_LEARNING_STATUSES.has(error.status) ||
      (error.status >= 500 && error.status <= 599))
  ) {
    return "retryable";
  }
  return error instanceof TypeError ? "retryable" : "terminal";
}

export type LearningLoadErrorPresentation = {
  errorClass: LearningLoadErrorClass;
  title: string;
  detail: string;
  requiresSignIn: boolean;
  requiresSupport: boolean;
  supportHref: string | null;
  canRetry: boolean;
};

export function getLearningLoadErrorPresentation(
  error: unknown,
): LearningLoadErrorPresentation {
  const errorClass = getLearningLoadErrorClass(error);
  const is401 = error instanceof ApiError && error.status === 401;
  const is403 = error instanceof ApiError && error.status === 403;
  const canRetry = errorClass === "retryable";
  return {
    errorClass,
    title: is401
      ? "Sign in to view your learning"
      : is403
        ? "You do not have access to this learner library"
        : canRetry
          ? "Learning library is temporarily unavailable"
          : "Could not load your courses",
    detail: is401
      ? "Your session has expired. Sign in again to view your courses."
      : is403
        ? "This account is not authorized to view this learner library. If you think this is incorrect, contact support."
        : canRetry
          ? "The learning service or network is temporarily unavailable. Retry the read; no learner work was changed."
          : userFacingRequestError(
              error,
              "The learning service could not be reached. Try again.",
            ),
    requiresSignIn: is401,
    requiresSupport: is403,
    supportHref: is403 ? LEARNER_SUPPORT_HREF : null,
    canRetry,
  };
}

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
  const offlineReadValues: unknown[] = [me];
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
    offlineReadValues.push(collection);
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
      getEarliestOfflineReadMetadata(...offlineReadValues, courses) ??
      undefined,
  };
}

function EmptyLearningState({
  filter,
  onClearFilter,
  tabLabelId,
}: {
  filter: LearningFilter;
  onClearFilter: () => void;
  tabLabelId: string;
}) {
  const filtered = filter !== "all";
  return (
    <section
      id="learning-course-list"
      className="card learning-collection-empty"
      role="tabpanel"
      aria-labelledby={tabLabelId}
      tabIndex={0}
      aria-describedby="learning-empty-title"
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

export function LearningFilterTabs({
  filter,
  savedFilterAvailable,
  onFilterChange,
}: {
  filter: LearningFilter;
  savedFilterAvailable: boolean;
  onFilterChange: (filter: LearningFilter) => void;
}) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const focusFilter = useCallback(
    (nextFilter: LearningFilter) => {
      const index = FILTERS.findIndex((item) => item.id === nextFilter);
      if (index === -1) return;
      tabRefs.current[index]?.focus();
      onFilterChange(nextFilter);
    },
    [onFilterChange],
  );

  return (
    <div
      className="learning-collection-tabs"
      role="tablist"
      aria-label="Filter courses"
      aria-orientation="horizontal"
    >
      {FILTERS.map((item, index) => {
        const disabled = item.id === "saved" && !savedFilterAvailable;
        const selected = filter === item.id;
        const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
          const target = getLearningFilterKeyboardTarget(
            item.id,
            event.key,
            savedFilterAvailable,
          );
          if (!target) return;
          event.preventDefault();
          focusFilter(target);
        };
        return (
          <button
            key={item.id}
            ref={(element) => {
              tabRefs.current[index] = element;
            }}
            id={`learning-filter-${item.id}`}
            className={`learning-collection-tab${selected ? " is-active" : ""}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls="learning-course-list"
            aria-disabled={disabled}
            tabIndex={selected ? 0 : -1}
            disabled={disabled}
            onKeyDown={handleKeyDown}
            onClick={() => onFilterChange(item.id)}
          >
            {item.label}
            {disabled ? " · unavailable" : null}
          </button>
        );
      })}
    </div>
  );
}

export function LearningLoadErrorState({
  presentation,
  onRetry,
}: {
  presentation: LearningLoadErrorPresentation;
  onRetry: () => void;
}) {
  return (
    <div
      className={`surface-state surface-state--error-${presentation.errorClass}`}
      data-error-class={presentation.errorClass}
      data-state={
        presentation.errorClass === "retryable"
          ? "ERROR_RETRYABLE"
          : "ERROR_TERMINAL"
      }
      role="alert"
    >
      <h1>{presentation.title}</h1>
      <p>{presentation.detail}</p>
      {presentation.requiresSignIn ? (
        <Link className="button button--ink" href={ROUTES.sessionExpired}>
          Sign in again
        </Link>
      ) : presentation.requiresSupport && presentation.supportHref ? (
        <a className="button button--outline" href={presentation.supportHref}>
          Contact learner support
        </a>
      ) : presentation.canRetry ? (
        <button
          className="button button--outline"
          type="button"
          onClick={onRetry}
        >
          <RotateCcw size={16} aria-hidden="true" /> Retry
        </button>
      ) : null}
    </div>
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
  const [offlineRead, setOfflineRead] = useState<
    OfflineReadMetadata | undefined
  >();
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
  const activeFilter =
    filter === "saved" && !savedFilterAvailable ? "all" : filter;

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
    return filterLearningCourses(courses, activeFilter, savedFilterAvailable);
  }, [activeFilter, courses, savedFilterAvailable]);

  if (loading) return <LearningSkeleton />;

  if (error) {
    return (
      <LearningLoadErrorState
        presentation={getLearningLoadErrorPresentation(error)}
        onRetry={() => void load()}
      />
    );
  }

  if (!me || !hasMembershipRole(me)) {
    return <MembershipUnavailable api={api} draftCleanup={draftCleanup} />;
  }

  return (
    <div className="learning-collection-view" data-testid="learning-collection">
      <RouteHeader
        className="learning-collection-header"
        title="My Learning"
        titleId="learning-collection-title"
        eyebrow={
          <span className="card-badge card-badge--primary">
            Learner library
          </span>
        }
        breadcrumbs={
          <nav className="learning-breadcrumbs" aria-label="Breadcrumb">
            <Link href={ROUTES.dashboard}>Dashboard</Link>
            <span aria-hidden="true">/</span>
            <span aria-current="page">My Learning</span>
          </nav>
        }
        description={
          offlineRead
            ? "Read-only snapshot of your learner library. Reconnect to verify access and enable live actions."
            : "Your server-authorized courses, organized around the published paths you can access."
        }
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
        <LearningFilterTabs
          filter={activeFilter}
          savedFilterAvailable={savedFilterAvailable}
          onFilterChange={setFilter}
        />
        <span className="learning-collection-count" aria-live="polite">
          {visibleCourses.length} shown
        </span>
      </div>

      {visibleCourses.length > 0 ? (
        <section
          id="learning-course-list"
          className="learning-course-list"
          role="tabpanel"
          aria-labelledby={`learning-filter-${activeFilter}`}
          tabIndex={0}
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
          filter={activeFilter}
          onClearFilter={() => setFilter("all")}
          tabLabelId={`learning-filter-${activeFilter}`}
        />
      )}
    </div>
  );
}
