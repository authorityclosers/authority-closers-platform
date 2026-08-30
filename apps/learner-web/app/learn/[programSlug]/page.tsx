import { ArrowRight, BookOpen, LockKeyhole } from "lucide-react";
import Link from "next/link";

import { CoursePath } from "../../components/course-path";
import { PreviewNotice } from "../../components/preview-notice";
import { Breadcrumbs, LearnerShell } from "../../components/site-shell";
import { ProgressMeter, StatusPill } from "../../components/shared-ui";
import { SurfaceStatePanel } from "../../components/surface-state";
import { getProgramBySlug } from "../../lib/course-data";
import { ROUTES } from "../../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../../lib/surface-state";

type ProgramLearningPageProps = {
  params: Promise<{ programSlug: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function ProgramLearningPage({
  params,
  searchParams,
}: ProgramLearningPageProps) {
  const { programSlug } = await params;
  const query = await searchParams;
  const program = getProgramBySlug(programSlug);
  const state = program ? parseSurfaceState(query.state) : "EMPTY";

  return (
    <LearnerShell current="course">
      <main id="main-content" className="learner-main">
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={ROUTES.programLearning(programSlug)}
            backHref={ROUTES.learnerHome}
          />
          {program && isContentVisible(state) ? (
            <>
              <Breadcrumbs
                items={[{ label: "Course" }, { label: program.title }]}
              />
              <PreviewNotice />
              <section
                className="learning-hero"
                aria-labelledby="learning-title"
              >
                <div className="learning-hero__copy">
                  <div className="inline-meta">
                    <StatusPill tone="acid">Preview path</StatusPill>
                    <span>Version seam · not connected</span>
                  </div>
                  <h1 id="learning-title">
                    {program.title}
                    <br />
                    <em>keep the thread.</em>
                  </h1>
                  <p>{program.description}</p>
                  <div className="learning-hero__links">
                    <Link
                      className="text-link"
                      href={ROUTES.activity("reflect")}
                    >
                      Open reflect preview{" "}
                      <ArrowRight size={15} aria-hidden="true" />
                    </Link>
                    <Link
                      className="text-link"
                      href={ROUTES.completion(program.slug)}
                    >
                      Completion gate{" "}
                      <LockKeyhole size={15} aria-hidden="true" />
                    </Link>
                  </div>
                </div>
                <aside
                  className="learning-hero__summary"
                  aria-label="Course preview summary"
                >
                  <div className="learning-hero__summary-icon">
                    <BookOpen size={20} aria-hidden="true" />
                  </div>
                  <p className="kicker">Illustrated progress</p>
                  <ProgressMeter
                    value={0}
                    label="Verified course progress"
                    detail="0 / 5 · preview only"
                  />
                  <p className="learning-hero__summary-note">
                    Renderer access is illustrated, but no activity has durable
                    completion evidence.
                  </p>
                </aside>
              </section>

              <section className="path-section" aria-labelledby="path-title">
                <div className="section-heading section-heading--split">
                  <div>
                    <p className="kicker">The path</p>
                    <h2 id="path-title">
                      Move in order.
                      <br />
                      <em>Leave evidence.</em>
                    </h2>
                  </div>
                  <p>
                    Each module keeps the next action visible. A locked step is
                    a real boundary, not a disabled decoration.
                  </p>
                </div>
                <CoursePath
                  programSlug={program.slug}
                  modules={program.modules}
                />
              </section>
            </>
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
