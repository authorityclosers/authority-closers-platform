"use client";

import {
  ChevronDown,
  Flame,
  Info,
  Layers3,
  LockKeyhole,
  Trophy,
} from "lucide-react";
import { useState } from "react";
import Link from "next/link";
import { ROUTES } from "../lib/routes";
import type { ReactNode } from "react";

import type {
  LearningCollectionResponse,
  LearningResponse,
} from "../lib/learner-api";

type ProgressScope = "course" | "all";

export type AllLearningRollup = {
  status: "available" | "unavailable";
  courseCount: number | null;
  completedCourseCount: number | null;
  completedActivities: number | null;
  requiredActivities: number | null;
  percentage: number | null;
  hasMore: boolean;
};

const UNAVAILABLE_COPY =
  "This signal is not available yet. It will appear only after its server-owned criteria and opt-in policy are published.";

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function percentageLabel(value: number | null): string {
  if (value === null) return "Unavailable";
  return `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`;
}

function courseProgress(learning: LearningResponse) {
  const projection = learning.projection;
  const completed = finiteNumber(projection.completed_count);
  const denominator = finiteNumber(projection.denominator);
  const percentage = finiteNumber(projection.percentage);

  return {
    completed,
    denominator,
    percentage,
  };
}

/**
 * Derive a display-only roll-up from the server's course collection projection.
 * A missing projection remains unavailable; it is never coerced to zero.
 */
export function buildAllLearningRollup(
  collection?: LearningCollectionResponse,
): AllLearningRollup {
  if (!collection) {
    return {
      status: "unavailable",
      courseCount: null,
      completedCourseCount: null,
      completedActivities: null,
      requiredActivities: null,
      percentage: null,
      hasMore: false,
    };
  }

  const courseCount = collection.items.length;
  const completedCourseCount = collection.items.filter(
    (course) => course.state === "completed",
  ).length;
  const projections = collection.items
    .map((course) => course.projection)
    .filter((projection): projection is NonNullable<typeof projection> =>
      Boolean(projection),
    );
  const everyCourseHasProjection = projections.length === courseCount;

  if (courseCount === 0) {
    return {
      status: "available",
      courseCount: 0,
      completedCourseCount: 0,
      completedActivities: null,
      requiredActivities: null,
      percentage: null,
      hasMore: Boolean(collection.next_cursor),
    };
  }

  if (!everyCourseHasProjection) {
    return {
      status: "available",
      courseCount,
      completedCourseCount,
      completedActivities: null,
      requiredActivities: null,
      percentage: null,
      hasMore: Boolean(collection.next_cursor),
    };
  }

  const completedActivities = projections.reduce(
    (total, projection) => total + Math.max(0, projection.completed_count),
    0,
  );
  const requiredActivities = projections.reduce(
    (total, projection) => total + Math.max(0, projection.denominator),
    0,
  );

  return {
    status: "available",
    courseCount,
    completedCourseCount,
    completedActivities,
    requiredActivities,
    percentage:
      requiredActivities > 0 ? completedActivities / requiredActivities : null,
    hasMore: Boolean(collection.next_cursor),
  };
}

function ScopeMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="progress-scope-metric">
      <dt>{label}</dt>
      <dd>
        <strong>{value}</strong>
        <span>{detail}</span>
      </dd>
    </div>
  );
}

function ScopeToggle({
  scope,
  onChange,
}: {
  scope: ProgressScope;
  onChange: (scope: ProgressScope) => void;
}) {
  return (
    <div
      className="progress-scope-toggle"
      role="group"
      aria-label="Progress scope"
    >
      <button
        className={scope === "course" ? "is-active" : undefined}
        type="button"
        aria-pressed={scope === "course"}
        onClick={() => onChange("course")}
      >
        This course
      </button>
      <button
        className={scope === "all" ? "is-active" : undefined}
        type="button"
        aria-pressed={scope === "all"}
        onClick={() => onChange("all")}
      >
        All learning
      </button>
    </div>
  );
}

function CourseScopeSnapshot({ learning }: { learning: LearningResponse }) {
  const progress = courseProgress(learning);

  return (
    <div className="progress-scope-snapshot" data-progress-scope="course">
      <div className="progress-scope-snapshot__lead">
        <span className="progress-scope-snapshot__icon" aria-hidden="true">
          <Layers3 size={19} />
        </span>
        <div>
          <p className="progress-scope-snapshot__eyebrow">
            Your current course
          </p>
          <h3>{learning.program_title}</h3>
          <p>Each completed required step counts toward this course.</p>
        </div>
      </div>
      <dl className="progress-scope-metrics">
        <ScopeMetric
          label="Completion"
          value={percentageLabel(progress.percentage)}
          detail="of required steps"
        />
        <ScopeMetric
          label="Activities"
          value={
            progress.completed !== null && progress.denominator !== null
              ? `${progress.completed} / ${progress.denominator}`
              : "Unavailable"
          }
          detail="steps completed"
        />
        <ScopeMetric
          label="Course version"
          value={`v${learning.version_number}`}
          detail="your enrolled version"
        />
      </dl>
      <Link
        className="button button--ink progress-scope-continue"
        href={ROUTES.programLearning(learning.program_slug)}
      >
        Continue learning
      </Link>
    </div>
  );
}

function AllLearningSnapshot({
  collection,
}: {
  collection?: LearningCollectionResponse;
}) {
  const rollup = buildAllLearningRollup(collection);

  if (rollup.status === "unavailable") {
    return (
      <div
        className="progress-scope-unavailable"
        role="status"
        data-progress-scope="all"
      >
        <span className="progress-scope-unavailable__icon" aria-hidden="true">
          <LockKeyhole size={18} />
        </span>
        <div>
          <strong>Your course summary couldn’t load</strong>
          <p>
            You can still view your current course. Try the full summary again
            later.
          </p>
        </div>
      </div>
    );
  }

  if (rollup.courseCount === 0) {
    return (
      <div
        className="progress-scope-unavailable"
        role="status"
        data-progress-scope="all"
      >
        <span className="progress-scope-unavailable__icon" aria-hidden="true">
          <Layers3 size={18} />
        </span>
        <div>
          <strong>No enrolled courses yet</strong>
          <p>Join a course to start tracking your learning here.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="progress-scope-snapshot" data-progress-scope="all">
      <div className="progress-scope-snapshot__lead">
        <span className="progress-scope-snapshot__icon" aria-hidden="true">
          <Layers3 size={19} />
        </span>
        <div>
          <p className="progress-scope-snapshot__eyebrow">
            {rollup.hasMore ? "Partial course summary" : "Your courses"}
          </p>
          <h3>All enrolled learning</h3>
          <p>A combined view of your enrolled courses and completed steps.</p>
        </div>
      </div>
      <dl className="progress-scope-metrics">
        <ScopeMetric
          label="Courses"
          value={String(rollup.courseCount)}
          detail="enrolled courses"
        />
        <ScopeMetric
          label="Completed courses"
          value={String(rollup.completedCourseCount)}
          detail="finished courses"
        />
        <ScopeMetric
          label="Activities"
          value={
            rollup.completedActivities !== null &&
            rollup.requiredActivities !== null
              ? `${rollup.completedActivities} / ${rollup.requiredActivities}`
              : "Unavailable"
          }
          detail="completed / required"
        />
        <ScopeMetric
          label="Completion"
          value={percentageLabel(rollup.percentage)}
          detail="across shown courses"
        />
      </dl>
      {rollup.completedActivities === null ? (
        <p className="progress-scope-snapshot__note">
          Some course totals are missing, so a combined completion total isn’t
          available yet.
        </p>
      ) : null}
      {rollup.hasMore ? (
        <p className="progress-scope-snapshot__note">
          More courses are available. These totals cover only the courses in
          this summary.
        </p>
      ) : null}
    </div>
  );
}

export function ProgressScopePanel({
  learning,
  collection,
}: {
  learning: LearningResponse;
  collection?: LearningCollectionResponse;
}) {
  const [scope, setScope] = useState<ProgressScope>("course");

  return (
    <section
      className="progress-scope-panel"
      aria-labelledby="progress-scope-title"
    >
      <div className="progress-scope-panel__header">
        <div>
          <h2 id="progress-scope-title">Learning progress</h2>
        </div>
        <ScopeToggle scope={scope} onChange={setScope} />
      </div>
      <div
        className="progress-scope-panel__body"
        aria-live="polite"
        aria-atomic="true"
      >
        {scope === "course" ? (
          <CourseScopeSnapshot learning={learning} />
        ) : (
          <AllLearningSnapshot collection={collection} />
        )}
      </div>
      <p className="progress-scope-panel__source">
        <Info size={14} aria-hidden="true" />
        <span>
          Completed steps track participation, not an assessment of your skills.
        </span>
      </p>
    </section>
  );
}

function FoundationCard({
  kind,
  icon,
  title,
  children,
}: {
  kind: "streak" | "achievement";
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <article
      className={`progress-foundation-card progress-foundation-card--${kind}`}
    >
      <div className="progress-foundation-card__topline">
        <span className="progress-foundation-card__icon" aria-hidden="true">
          {icon}
        </span>
        <span className="progress-foundation-card__status">Unavailable</span>
      </div>
      <div className="progress-foundation-card__copy">
        <p className="kicker">{title}</p>
        <strong aria-label={`${title} value unavailable`}>Not available</strong>
        <p>{children}</p>
      </div>
      <details className="progress-foundation-card__details">
        <summary>
          <span>Why no number yet</span>
          <ChevronDown size={15} aria-hidden="true" />
        </summary>
        <p>{UNAVAILABLE_COPY}</p>
      </details>
    </article>
  );
}

/**
 * A visual foundation for future opt-in motivation signals. It deliberately
 * exposes no client-owned streak, XP, badge, score, or reward value.
 */
export function ProgressMotivationPanel() {
  return (
    <section
      className="progress-motivation-panel"
      aria-labelledby="progress-motivation-title"
    >
      <div className="progress-motivation-panel__header">
        <div>
          <p className="kicker">Motivation foundations</p>
          <h2 id="progress-motivation-title">
            Momentum, with clear guardrails.
          </h2>
          <p>
            These opt-in surfaces are ready for a future server contract. Your
            current progress never depends on them.
          </p>
        </div>
        <span className="progress-motivation-panel__badge">
          <Info size={14} aria-hidden="true" />
          No score or ranking
        </span>
      </div>
      <div className="progress-foundation-grid">
        <FoundationCard kind="streak" title="Streak" icon={<Flame size={20} />}>
          No activity rhythm is shown until its criteria, timezone, and recovery
          behavior are server-authorized.
        </FoundationCard>
        <FoundationCard
          kind="achievement"
          title="Achievements"
          icon={<Trophy size={20} />}
        >
          Badges remain opt-in until their criteria, issuance, and visibility
          rules are published for this learning context.
        </FoundationCard>
      </div>
    </section>
  );
}
