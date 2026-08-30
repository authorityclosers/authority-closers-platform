import { ArrowLeft, ArrowRight, CircleHelp, LockKeyhole } from "lucide-react";
import Link from "next/link";

import { ActivityRenderer } from "../../components/activity-renderers";
import { PreviewNotice } from "../../components/preview-notice";
import { Breadcrumbs, LearnerShell } from "../../components/site-shell";
import { ActivityStatusPill, StatusPill } from "../../components/shared-ui";
import { SurfaceStatePanel } from "../../components/surface-state";
import {
  freeCourse,
  getActivityLocationById,
  isActivityPayloadAllowed,
} from "../../lib/course-data";
import { ROUTES } from "../../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../../lib/surface-state";

type ActivityPageProps = {
  params: Promise<{ activityId: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ActivityPage({
  params,
  searchParams,
}: ActivityPageProps) {
  const { activityId } = await params;
  const query = await searchParams;
  const activityLocation = getActivityLocationById(activityId);
  const activity = activityLocation?.activity;
  const payloadAllowed = isActivityPayloadAllowed(activityLocation);
  const state = !activity
    ? "EMPTY"
    : payloadAllowed
      ? parseSurfaceState(query.state)
      : "LOCKED";
  const activityIndex = activity
    ? freeCourse.modules
        .flatMap((module) => module.activities)
        .findIndex((item) => item.id === activity.id)
    : -1;
  const canonicalNextActivity =
    activityIndex >= 0
      ? freeCourse.modules.flatMap((module) => module.activities)[
          activityIndex + 1
        ]
      : undefined;
  const nextActivityLocation = canonicalNextActivity
    ? getActivityLocationById(canonicalNextActivity.id)
    : undefined;
  const nextActivity = isActivityPayloadAllowed(nextActivityLocation)
    ? canonicalNextActivity
    : undefined;

  return (
    <LearnerShell current="course">
      <main id="main-content" className="learner-main">
        <div className="page-container activity-page">
          <SurfaceStatePanel
            state={state}
            retryHref={ROUTES.activity(activityId)}
            backHref={ROUTES.programLearning(freeCourse.slug)}
          />
          {activity && payloadAllowed && isContentVisible(state) ? (
            <>
              <Breadcrumbs
                items={[
                  {
                    label: "Course",
                    href: ROUTES.programLearning(freeCourse.slug),
                  },
                  { label: activity.eyebrow },
                  { label: activity.title },
                ]}
              />
              <PreviewNotice />
              <section
                className="activity-hero"
                aria-labelledby="activity-title"
              >
                <div>
                  <Link
                    className="text-link"
                    href={ROUTES.programLearning(freeCourse.slug)}
                  >
                    <ArrowLeft size={15} aria-hidden="true" /> Back to course
                    path
                  </Link>
                  <p className="eyebrow">
                    <span aria-hidden="true" /> Activity{" "}
                    {String(activity.order).padStart(2, "0")} ·{" "}
                    {activity.eyebrow}
                  </p>
                  <h1 id="activity-title">
                    {activity.title}
                    <br />
                    <em>make the moment useful.</em>
                  </h1>
                  <p>{activity.objective}</p>
                </div>
                <aside
                  className="activity-hero__meta"
                  aria-label="Activity details"
                >
                  <ActivityStatusPill status={activity.status} />
                  <span>{activity.duration}</span>
                  <StatusPill tone="neutral">Renderer preview</StatusPill>
                </aside>
              </section>

              <div className="activity-layout">
                <section
                  className="activity-shell"
                  aria-labelledby="activity-work-title"
                >
                  <div className="activity-shell__header">
                    <div>
                      <p className="kicker">{activity.eyebrow} · guided work</p>
                      <h2 id="activity-work-title">Your turn.</h2>
                    </div>
                    <span className="activity-shell__step">
                      {activity.order} / 5
                    </span>
                  </div>
                  <ActivityRenderer activity={activity} />
                </section>
                <aside className="activity-brief" aria-labelledby="brief-title">
                  <div className="activity-brief__icon">
                    <CircleHelp size={20} aria-hidden="true" />
                  </div>
                  <p className="kicker">Before you begin</p>
                  <h2 id="brief-title">Know what counts.</h2>
                  <dl>
                    <div>
                      <dt>Purpose</dt>
                      <dd>{activity.prompt}</dd>
                    </div>
                    <div>
                      <dt>Evidence seam</dt>
                      <dd>{activity.evidenceLabel}</dd>
                    </div>
                    <div>
                      <dt>Persistence</dt>
                      <dd>
                        Not connected. Leave this preview assuming any local
                        input will be lost.
                      </dd>
                    </div>
                  </dl>
                </aside>
              </div>

              <div className="activity-footer-nav">
                <Link
                  className="text-link"
                  href={ROUTES.programLearning(freeCourse.slug)}
                >
                  <ArrowLeft size={15} aria-hidden="true" /> Return to course
                  path
                </Link>
                {nextActivity ? (
                  <Link
                    className="button button--ink"
                    href={ROUTES.activity(nextActivity.id)}
                  >
                    Next activity <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                ) : canonicalNextActivity ? (
                  <span
                    className="button button--outline button--disabled"
                    aria-disabled="true"
                  >
                    <LockKeyhole size={16} aria-hidden="true" /> Next activity
                    locked
                  </span>
                ) : (
                  <Link
                    className="button button--ink"
                    href={ROUTES.completion(freeCourse.slug)}
                  >
                    View completion gate{" "}
                    <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                )}
              </div>
            </>
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
