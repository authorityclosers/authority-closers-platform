import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  Clock3,
  LockKeyhole,
} from "lucide-react";
import Link from "next/link";

import { PreviewNotice } from "../../components/preview-notice";
import { PublicShell } from "../../components/site-shell";
import { SurfaceStatePanel } from "../../components/surface-state";
import { activityKindLabel, getProgramBySlug } from "../../lib/course-data";
import { ROUTES } from "../../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../../lib/surface-state";
import type { ProgramViewModel } from "../../lib/view-models";

type ProgramDetailPageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

function ProgramFacts({ program }: { program: ProgramViewModel }) {
  return (
    <dl className="fact-grid">
      <div>
        <dt>Format</dt>
        <dd>{program.formatLabel}</dd>
      </div>
      <div>
        <dt>Sequence</dt>
        <dd>Sequential modules</dd>
      </div>
      <div>
        <dt>Access</dt>
        <dd>Free course preview</dd>
      </div>
    </dl>
  );
}

export default async function ProgramDetailPage({
  params,
  searchParams,
}: ProgramDetailPageProps) {
  const { slug } = await params;
  const query = await searchParams;
  const program = getProgramBySlug(slug);
  const state = program ? parseSurfaceState(query.state) : "EMPTY";

  return (
    <PublicShell current="program">
      <main id="main-content" className="public-main">
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={ROUTES.programDetail(slug)}
            backHref={ROUTES.home}
          />
          {program && isContentVisible(state) ? (
            <>
              <div className="page-topline">
                <Link className="text-link" href={ROUTES.home}>
                  <ArrowLeft size={15} aria-hidden="true" /> Back to overview
                </Link>
                <span className="topline-note">{program.previewLabel}</span>
              </div>
              <section className="program-hero" aria-labelledby="program-title">
                <div className="program-hero__main">
                  <p className="eyebrow">
                    <span aria-hidden="true" /> {program.eyebrow}
                  </p>
                  <h1 id="program-title">
                    {program.title}
                    <br />
                    <em>for the next conversation.</em>
                  </h1>
                  <p className="program-hero__description">
                    {program.shortDescription}
                  </p>
                  <div className="hero-actions">
                    <Link
                      className="button button--ink"
                      href={ROUTES.onboarding}
                    >
                      Enter the preview{" "}
                      <ArrowUpRight size={18} aria-hidden="true" />
                    </Link>
                    <Link
                      className="text-link text-link--large"
                      href={ROUTES.programLearning(program.slug)}
                    >
                      View learning path{" "}
                      <ArrowRight size={17} aria-hidden="true" />
                    </Link>
                  </div>
                </div>
                <aside
                  className="program-hero__aside"
                  aria-label="Program facts"
                >
                  <div className="program-hero__aside-mark">01</div>
                  <p>One idea, carried from attention to action.</p>
                  <ProgramFacts program={program} />
                </aside>
              </section>

              <PreviewNotice />

              <section
                className="detail-section"
                aria-labelledby="outcome-title"
              >
                <div className="section-heading">
                  <p className="kicker">What this preview holds</p>
                  <h2 id="outcome-title">
                    The work is small
                    <br />
                    <em>on purpose.</em>
                  </h2>
                </div>
                <div className="detail-copy-grid">
                  <p>{program.description}</p>
                  <div className="boundary-card">
                    <span className="boundary-card__icon">
                      <LockKeyhole size={17} aria-hidden="true" />
                    </span>
                    <strong>No paid handoff here.</strong>
                    <span>
                      Checkout remains capability-gated in this first slice.
                      This button enters a preview workspace only.
                    </span>
                  </div>
                </div>
              </section>

              <section className="detail-section" aria-labelledby="loop-title">
                <div className="section-heading section-heading--split">
                  <div>
                    <p className="kicker">The course loop</p>
                    <h2 id="loop-title">
                      Five ways to stay
                      <br />
                      <em>in the room.</em>
                    </h2>
                  </div>
                  <p>
                    Each activity creates a different kind of learner evidence.
                    Drafts and official completion stay separate.
                  </p>
                </div>
                <ol className="detail-loop">
                  {program.learningLoop.map((step, index) => (
                    <li key={step}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <strong>{step}</strong>
                      <span>
                        {index === 0
                          ? "Static transcript copy."
                          : index === 1
                            ? "A private question."
                            : index === 2
                              ? "A practice scenario."
                              : index === 3
                                ? "Human-authored criteria."
                                : "A repeatable adjustment."}
                      </span>
                    </li>
                  ))}
                </ol>
              </section>

              <section
                className="program-modules"
                aria-labelledby="modules-title"
              >
                <div className="section-heading section-heading--split">
                  <div>
                    <p className="kicker">Permanent hierarchy</p>
                    <h2 id="modules-title">Program → Module → Activity</h2>
                  </div>
                  <p>
                    Published versions can evolve without making a
                    learner&apos;s pinned path ambiguous.
                  </p>
                </div>
                <div className="public-module-grid">
                  {program.modules.map((module) => (
                    <article
                      className={`public-module-card${module.status === "LOCKED" ? " is-locked" : ""}`}
                      key={module.id}
                    >
                      <div className="public-module-card__topline">
                        <span>Module {module.number}</span>
                        {module.status === "LOCKED" ? (
                          <LockKeyhole size={15} aria-label="Locked" />
                        ) : (
                          <Check size={15} aria-label="Available" />
                        )}
                      </div>
                      <h3>{module.title}</h3>
                      <p>{module.summary}</p>
                      <ul>
                        {module.activities.map((activity) => (
                          <li key={activity.id}>
                            <span className="activity-dot" aria-hidden="true" />
                            {activityKindLabel(activity.kind)}
                            <span>{activity.duration}</span>
                          </li>
                        ))}
                      </ul>
                      <span className="public-module-card__footer">
                        {module.prerequisite}
                      </span>
                    </article>
                  ))}
                </div>
              </section>

              <section className="closing-cta" aria-labelledby="closing-title">
                <div>
                  <Clock3 size={21} aria-hidden="true" />
                  <span>
                    Approx. 15 minutes to a first meaningful rep · preview
                    guidance
                  </span>
                </div>
                <h2 id="closing-title">
                  Start with one
                  <br />
                  <em>honest question.</em>
                </h2>
                <Link className="button button--acid" href={ROUTES.onboarding}>
                  Open the preview workspace{" "}
                  <ArrowRight size={17} aria-hidden="true" />
                </Link>
              </section>
            </>
          ) : null}
        </div>
      </main>
    </PublicShell>
  );
}
