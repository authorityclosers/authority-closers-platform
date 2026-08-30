import { ArrowUpRight, ChevronRight, LockKeyhole } from "lucide-react";
import Link from "next/link";

import { activityKindLabel } from "../lib/course-data";
import { ROUTES } from "../lib/routes";
import type { ActivityViewModel, ModuleViewModel } from "../lib/view-models";
import { ActivityKindIcon, ActivityStatusPill, StatusPill } from "./shared-ui";

export function ActivityRow({
  activity,
  programSlug,
  parentLocked = false,
}: {
  activity: ActivityViewModel;
  programSlug: string;
  parentLocked?: boolean;
}) {
  const isLocked = parentLocked || activity.status === "LOCKED";
  const content = (
    <>
      <span className="activity-row__order">
        {String(activity.order).padStart(2, "0")}
      </span>
      <span className="activity-row__icon">
        <ActivityKindIcon kind={activity.kind} />
      </span>
      <span className="activity-row__copy">
        <span className="activity-row__eyebrow">
          {activity.eyebrow} · {activity.duration}
        </span>
        <strong>{activity.title}</strong>
        <span className="activity-row__objective">{activity.objective}</span>
      </span>
      <span className="activity-row__status">
        <ActivityStatusPill status={isLocked ? "LOCKED" : activity.status} />
        {isLocked ? (
          <LockKeyhole size={16} aria-hidden="true" />
        ) : (
          <ChevronRight size={17} aria-hidden="true" />
        )}
      </span>
    </>
  );

  return (
    <li className={`activity-row${isLocked ? " activity-row--locked" : ""}`}>
      {isLocked ? (
        <div
          className="activity-row__locked-content"
          aria-label={`${activity.order}. ${activity.title}, locked`}
          aria-disabled="true"
        >
          {content}
        </div>
      ) : (
        <Link
          href={ROUTES.activity(activity.id)}
          aria-label={`${activity.order}. ${activity.title}, ${activityKindLabel(activity.kind)}`}
        >
          {content}
        </Link>
      )}
      <span className="sr-only">Program: {programSlug}</span>
    </li>
  );
}

export function ModuleCard({
  module,
  programSlug,
}: {
  module: ModuleViewModel;
  programSlug: string;
}) {
  const isLocked = module.status === "LOCKED";

  return (
    <section
      className={`module-card${isLocked ? " module-card--locked" : ""}`}
      aria-labelledby={`${module.id}-title`}
    >
      <div className="module-card__header">
        <div>
          <p className="module-card__number">Module {module.number}</p>
          <h2 id={`${module.id}-title`}>{module.title}</h2>
        </div>
        <StatusPill
          tone={
            isLocked
              ? "muted"
              : module.status === "COMPLETED"
                ? "acid"
                : "neutral"
          }
        >
          {isLocked ? <LockKeyhole size={13} aria-hidden="true" /> : null}
          {isLocked
            ? "Locked"
            : module.status === "COMPLETED"
              ? "Complete"
              : "Available"}
        </StatusPill>
      </div>
      <p className="module-card__summary">{module.summary}</p>
      <p className="module-card__prerequisite">{module.prerequisite}</p>
      <ol className="activity-list">
        {module.activities.map((activity) => (
          <ActivityRow
            key={activity.id}
            activity={activity}
            programSlug={programSlug}
            parentLocked={isLocked}
          />
        ))}
      </ol>
      {!isLocked ? (
        <Link
          className="module-card__footer-link"
          href={ROUTES.module(programSlug, module.id)}
        >
          Open module <ArrowUpRight size={15} aria-hidden="true" />
        </Link>
      ) : null}
    </section>
  );
}

export function CoursePath({
  programSlug,
  modules,
}: {
  programSlug: string;
  modules: ModuleViewModel[];
}) {
  return (
    <div className="course-path">
      {modules.map((module) => (
        <ModuleCard key={module.id} module={module} programSlug={programSlug} />
      ))}
    </div>
  );
}
