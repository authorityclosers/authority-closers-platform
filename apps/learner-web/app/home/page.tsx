import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Clock3,
  FileText,
  Orbit,
} from "lucide-react";
import Link from "next/link";

import { PreviewNotice } from "../components/preview-notice";
import { LearnerShell } from "../components/site-shell";
import { ProgressMeter, StatusPill } from "../components/shared-ui";
import { SurfaceStatePanel } from "../components/surface-state";
import { demoLearner, freeCourse, getActivityById } from "../lib/course-data";
import { ROUTES } from "../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../lib/surface-state";

type LearnerHomePageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function LearnerHomePage({
  searchParams,
}: LearnerHomePageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);
  const nextActivity = getActivityById(demoLearner.nextActivityId);

  return (
    <LearnerShell current="home">
      <main id="main-content" className="learner-main">
        <div className="page-container home-page">
          <SurfaceStatePanel
            state={state}
            retryHref={ROUTES.learnerHome}
            backHref={ROUTES.home}
          />
          {isContentVisible(state) ? (
            <>
              <PreviewNotice />
              <section
                className="dashboard-intro"
                aria-labelledby="dashboard-title"
              >
                <div>
                  <p className="eyebrow">
                    <span aria-hidden="true" /> {demoLearner.workspaceLabel}
                  </p>
                  <h1 id="dashboard-title">
                    Learner home,
                    <br />
                    <em>before live data.</em>
                  </h1>
                </div>
                <div className="dashboard-intro__note">
                  <Orbit size={19} aria-hidden="true" />
                  <span>Keep the next move small enough to repeat.</span>
                </div>
              </section>

              <div className="dashboard-grid">
                <section
                  className="current-course-card"
                  aria-labelledby="current-course-title"
                >
                  <div className="current-course-card__topline">
                    <span className="kicker">Course preview</span>
                    <StatusPill tone="neutral">Preview only</StatusPill>
                  </div>
                  <div className="current-course-card__body">
                    <p className="module-card__number">
                      Module 01 · Find the signal
                    </p>
                    <h2 id="current-course-title">{freeCourse.title}</h2>
                    <p>{freeCourse.shortDescription}</p>
                    <ProgressMeter
                      value={0}
                      label="Verified course progress"
                      detail="0 / 5 · preview only"
                    />
                    <div className="current-course-card__actions">
                      <Link
                        className="button button--ink"
                        href={ROUTES.activity(nextActivity?.id ?? "reflect")}
                      >
                        Open {nextActivity?.eyebrow.toLowerCase() ?? "reflect"}{" "}
                        preview <ArrowRight size={17} aria-hidden="true" />
                      </Link>
                      <Link
                        className="text-link"
                        href={ROUTES.programLearning(freeCourse.slug)}
                      >
                        View full path{" "}
                        <ArrowUpRight size={15} aria-hidden="true" />
                      </Link>
                    </div>
                  </div>
                </section>

                <aside
                  className="first-win-card"
                  aria-labelledby="first-win-title"
                >
                  <div className="first-win-card__icon">
                    <Clock3 size={20} aria-hidden="true" />
                  </div>
                  <p className="kicker">Your first win</p>
                  <h2 id="first-win-title">
                    Leave with one sentence you can use.
                  </h2>
                  <p>
                    Start with the moment you noticed. The practice loop will
                    give it somewhere to go.
                  </p>
                  <span className="first-win-card__footer">
                    Approx. 15 minutes · preview guidance
                  </span>
                </aside>
              </div>

              <section className="dashboard-lower" aria-labelledby="work-title">
                <div className="dashboard-lower__heading">
                  <div>
                    <p className="kicker">Your workspace</p>
                    <h2 id="work-title">Keep the thread.</h2>
                  </div>
                  <span className="dashboard-lower__caption">
                    No live metrics in preview mode
                  </span>
                </div>
                <div className="workspace-grid">
                  <article className="workspace-card workspace-card--draft">
                    <div className="workspace-card__icon">
                      <FileText size={18} aria-hidden="true" />
                    </div>
                    <p className="kicker">Persistence seam</p>
                    <h3>No saved draft</h3>
                    <p>{demoLearner.draftSeamLabel}</p>
                    <Link
                      className="text-link"
                      href={ROUTES.activity("reflect")}
                    >
                      Open reflect preview{" "}
                      <ArrowRight size={15} aria-hidden="true" />
                    </Link>
                  </article>
                  <article className="workspace-card workspace-card--next">
                    <div className="workspace-card__icon">
                      <Check size={18} aria-hidden="true" />
                    </div>
                    <p className="kicker">What happens next</p>
                    <h3>Try, then make it legible.</h3>
                    <p>
                      After the practice prompt, review stays human-authored and
                      evidence stays explainable.
                    </p>
                    <Link
                      className="text-link"
                      href={ROUTES.programLearning(freeCourse.slug)}
                    >
                      See the sequence{" "}
                      <ArrowRight size={15} aria-hidden="true" />
                    </Link>
                  </article>
                </div>
              </section>
            </>
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
