import { ArrowLeft, ArrowRight, BookOpen, LockKeyhole } from "lucide-react";
import Link from "next/link";

import { ActivityRow } from "../../../../components/course-path";
import { PreviewNotice } from "../../../../components/preview-notice";
import { Breadcrumbs, LearnerShell } from "../../../../components/site-shell";
import { StatusPill } from "../../../../components/shared-ui";
import { SurfaceStatePanel } from "../../../../components/surface-state";
import {
  getModuleById,
  getProgramBySlug,
  isModulePayloadAllowed,
} from "../../../../lib/course-data";
import { ROUTES } from "../../../../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../../../../lib/surface-state";

type ModulePageProps = {
  params: Promise<{ programSlug: string; moduleId: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ModulePage({
  params,
  searchParams,
}: ModulePageProps) {
  const { programSlug, moduleId } = await params;
  const query = await searchParams;
  const program = getProgramBySlug(programSlug);
  const courseModule = program ? getModuleById(program, moduleId) : undefined;
  const payloadAllowed = isModulePayloadAllowed(courseModule);
  const state =
    !program || !courseModule
      ? "EMPTY"
      : payloadAllowed
        ? parseSurfaceState(query.state)
        : "LOCKED";

  return (
    <LearnerShell current="course">
      <main id="main-content" className="learner-main">
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={ROUTES.module(programSlug, moduleId)}
            backHref={ROUTES.programLearning(programSlug)}
          />
          {program &&
          courseModule &&
          payloadAllowed &&
          isContentVisible(state) ? (
            <>
              <Breadcrumbs
                items={[
                  {
                    label: "Course",
                    href: ROUTES.programLearning(program.slug),
                  },
                  { label: `Module ${courseModule.number}` },
                  { label: courseModule.title },
                ]}
              />
              <PreviewNotice />
              <section className="module-hero" aria-labelledby="module-title">
                <div>
                  <Link
                    className="text-link"
                    href={ROUTES.programLearning(program.slug)}
                  >
                    <ArrowLeft size={15} aria-hidden="true" /> Back to course
                    path
                  </Link>
                  <p className="eyebrow">
                    <span aria-hidden="true" /> Module {courseModule.number}
                  </p>
                  <h1 id="module-title">
                    {courseModule.title}
                    <br />
                    <em>one useful move at a time.</em>
                  </h1>
                  <p>{courseModule.summary}</p>
                </div>
                <aside
                  className="module-hero__aside"
                  aria-label="Module status"
                >
                  <div className="module-hero__icon">
                    <BookOpen size={21} aria-hidden="true" />
                  </div>
                  <StatusPill
                    tone={courseModule.status === "LOCKED" ? "muted" : "acid"}
                  >
                    {courseModule.status === "LOCKED" ? (
                      <LockKeyhole size={13} aria-hidden="true" />
                    ) : null}
                    {courseModule.status === "LOCKED" ? "Locked" : "Available"}
                  </StatusPill>
                  <p>{courseModule.prerequisite}</p>
                </aside>
              </section>

              <section
                className="module-activities"
                aria-labelledby="module-activities-title"
              >
                <div className="section-heading section-heading--split">
                  <div>
                    <p className="kicker">Module sequence</p>
                    <h2 id="module-activities-title">
                      Do the next
                      <br />
                      <em>visible thing.</em>
                    </h2>
                  </div>
                  <p>
                    {courseModule.activities.length} activity renderers, each
                    with its own evidence seam and recovery state.
                  </p>
                </div>
                <ol className="activity-list activity-list--large">
                  {courseModule.activities.map((activity) => (
                    <ActivityRow
                      key={activity.id}
                      activity={activity}
                      programSlug={program.slug}
                    />
                  ))}
                </ol>
              </section>

              <div className="module-footer-nav">
                <Link
                  className="text-link"
                  href={ROUTES.programLearning(program.slug)}
                >
                  <ArrowLeft size={15} aria-hidden="true" /> Course overview
                </Link>
                <Link
                  className="button button--ink"
                  href={ROUTES.activity(
                    courseModule.activities[0]?.id ?? "watch",
                  )}
                >
                  Open first activity{" "}
                  <ArrowRight size={16} aria-hidden="true" />
                </Link>
              </div>
            </>
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
