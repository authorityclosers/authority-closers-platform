import { ArrowRight, BookOpen, Bookmark, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { ProgramCard, ProgressMeter } from "@ac/ui";

import type { LearningCourseSummaryResponse } from "../lib/learner-api";
import { ROUTES } from "../lib/routes";

export type CourseNextAction = {
  id: "continue" | "review" | "open";
  label: string;
  detail: string;
};

/**
 * Pick the learner-facing action from the server's course state only.
 *
 * The collection contract intentionally does not expose an activity route or
 * a client-selected next item. Every action therefore stays on the existing
 * slug-shaped program route, where the server re-checks current access and
 * destination state before showing the course path.
 */
export function getCourseNextAction(
  state: LearningCourseSummaryResponse["state"],
): CourseNextAction {
  if (state === "in_progress") {
    return {
      id: "continue",
      label: "Continue course",
      detail: "Resume the published course path from your current progress.",
    };
  }

  if (state === "completed") {
    return {
      id: "review",
      label: "Review course",
      detail: "Revisit the published course path and completed activities.",
    };
  }

  return {
    id: "open",
    label: "Open course",
    detail:
      "Open the published course path to re-check current access and progress.",
  };
}

export function getCourseStateLabel(
  state: LearningCourseSummaryResponse["state"],
): string {
  if (state === "in_progress") return "In progress";
  if (state === "completed") return "Completed";
  return "Progress unavailable";
}

export function getCourseStateClass(
  state: LearningCourseSummaryResponse["state"],
): string {
  return `learning-course-card--${state.replaceAll("_", "-")}`;
}

export function getCourseProjection(course: LearningCourseSummaryResponse): {
  value: number | null;
  detail: string;
} {
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

function formatEnrolledDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Enrollment date unavailable";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function CourseStateBadge({
  state,
  saved,
}: {
  state: LearningCourseSummaryResponse["state"];
  saved: boolean;
}) {
  return (
    <div
      className="learning-course-card__badges"
      role="group"
      aria-label="Course status"
    >
      <span
        className={`learning-course-state learning-course-state--${state.replaceAll("_", "-")}`}
        data-course-state={state}
      >
        {state === "completed" ? (
          <CheckCircle2 size={14} aria-hidden="true" />
        ) : null}
        <span>{getCourseStateLabel(state)}</span>
      </span>
      {saved ? (
        <span className="learning-course-state learning-course-state--saved">
          <Bookmark size={14} aria-hidden="true" />
          <span>Saved</span>
        </span>
      ) : null}
    </div>
  );
}

/** A reusable learner-owned course card for the My Learning collection. */
export function LearningCourseCard({
  course,
  index,
}: {
  course: LearningCourseSummaryResponse;
  index: number;
}) {
  const progress = getCourseProjection(course);
  const nextAction = getCourseNextAction(course.state);
  const titleId = `learning-course-${course.program_id}-${course.program_version_id}`;
  const href = ROUTES.programLearning(course.program_slug);

  return (
    <ProgramCard
      className={`learning-course-card ${getCourseStateClass(course.state)}`}
      title={course.program_title}
      titleId={titleId}
      titleAs="h2"
      eyebrow={`Course ${String(index + 1).padStart(2, "0")}`}
      badges={
        <CourseStateBadge
          state={course.state}
          saved={course.saved_state === "saved"}
        />
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
      description="Follow the published course path; the destination determines the current learner action."
      meta={
        <span>
          Version {course.version_number} · Enrolled{" "}
          {formatEnrolledDate(course.enrolled_at)}
        </span>
      }
      action={
        <Link
          className="button button--cobalt learning-course-card__action-link"
          href={href}
          aria-label={`${nextAction.label}: ${course.program_title}`}
          data-course-href={href}
          data-next-action={nextAction.id}
        >
          {nextAction.label} <ArrowRight size={16} aria-hidden="true" />
        </Link>
      }
    >
      <ProgressMeter
        value={progress.value}
        label="Course progress"
        detail={progress.detail}
      />
      <div
        className="learning-course-card__next-action"
        data-next-action={nextAction.id}
        aria-label={`Next action: ${nextAction.label}`}
      >
        <span className="learning-course-card__next-action-label">
          Next action
        </span>
        <strong>{nextAction.detail}</strong>
      </div>
    </ProgramCard>
  );
}
