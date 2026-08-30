import {
  ArrowRight,
  ArrowUpRight,
  CirclePlay,
  Layers3,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import { freeCourse } from "./lib/course-data";
import { ROUTES } from "./lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "./lib/surface-state";
import { PreviewNotice } from "./components/preview-notice";
import { PublicShell } from "./components/site-shell";
import { SurfaceStatePanel } from "./components/surface-state";

type HomePageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <PublicShell>
      <main id="main-content" className="public-main">
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={ROUTES.home}
            backHref={ROUTES.home}
          />
          {isContentVisible(state) ? (
            <>
              <section
                id="top"
                className="hero landing-hero"
                aria-labelledby="home-title"
              >
                <div className="eyebrow">
                  <span aria-hidden="true" /> The practice floor for high-stakes
                  conversations
                </div>
                <h1 id="home-title">
                  Stop collecting advice.
                  <br />
                  <em>Build the instinct.</em>
                </h1>
                <p className="hero-copy">
                  A focused learning preview where every lesson becomes a
                  question, every attempt becomes easier to explain, and the
                  next step stays visible.
                </p>
                <div className="hero-actions">
                  <Link
                    className="button button--ink"
                    href={ROUTES.programDetail(freeCourse.slug)}
                  >
                    Begin the free course{" "}
                    <ArrowUpRight size={18} aria-hidden="true" />
                  </Link>
                  <a className="text-link text-link--large" href="#method">
                    <CirclePlay size={19} aria-hidden="true" /> See the practice
                    loop
                  </a>
                </div>
                <PreviewNotice />
              </section>

              <section
                id="method"
                className="method-section"
                aria-labelledby="method-title"
              >
                <div className="section-heading section-heading--split">
                  <div>
                    <p className="kicker">The method</p>
                    <h2 id="method-title">
                      A loop that leaves
                      <br />
                      <em>something behind.</em>
                    </h2>
                  </div>
                  <p>
                    Practice is only useful when it changes what you can notice
                    and do next.
                  </p>
                </div>
                <ol className="method-grid">
                  {freeCourse.learningLoop.map((step, index) => (
                    <li
                      key={step}
                      className={
                        index === freeCourse.learningLoop.length - 1
                          ? "is-accent"
                          : undefined
                      }
                    >
                      <span className="method-grid__index">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <strong>{step}</strong>
                      <span>
                        {index === 0
                          ? "See the moment."
                          : index === 1
                            ? "Name the signal."
                            : index === 2
                              ? "Try the move."
                              : index === 3
                                ? "Make it legible."
                                : "Choose the next rep."}
                      </span>
                    </li>
                  ))}
                </ol>
              </section>

              <section
                className="feature-section"
                aria-labelledby="feature-title"
              >
                <div className="feature-section__copy">
                  <p className="kicker">
                    First slice · {freeCourse.previewLabel}
                  </p>
                  <h2 id="feature-title">
                    Less content.
                    <br />
                    <em>More contact.</em>
                  </h2>
                  <p>{freeCourse.description}</p>
                  <Link
                    className="text-link"
                    href={ROUTES.programDetail(freeCourse.slug)}
                  >
                    View the course detail{" "}
                    <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                </div>
                <div
                  className="feature-section__stamp"
                  aria-label="Course preview details"
                >
                  <div className="stamp-icon">
                    <Layers3 size={24} aria-hidden="true" />
                  </div>
                  <strong>Watch → reflect → implement</strong>
                  <span>{freeCourse.formatLabel}</span>
                  <span>
                    Built for a first meaningful rep, not a content library.
                  </span>
                </div>
              </section>

              <section className="trust-strip" aria-label="Preview boundaries">
                <div>
                  <ShieldCheck size={18} aria-hidden="true" />
                  <span>Named identity in the connected flow</span>
                </div>
                <div>
                  <Layers3 size={18} aria-hidden="true" />
                  <span>Versioned course hierarchy</span>
                </div>
                <div>
                  <CirclePlay size={18} aria-hidden="true" />
                  <span>Static transcript integration seam</span>
                </div>
              </section>
            </>
          ) : null}
        </div>
      </main>
    </PublicShell>
  );
}
