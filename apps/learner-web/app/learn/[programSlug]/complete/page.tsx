import { ArrowLeft, Award, LockKeyhole } from "lucide-react";
import Link from "next/link";

import { CompletionChecklist } from "../../../components/completion-checklist";
import { PreviewNotice } from "../../../components/preview-notice";
import { Breadcrumbs, LearnerShell } from "../../../components/site-shell";
import { SurfaceStatePanel } from "../../../components/surface-state";
import { getProgramBySlug } from "../../../lib/course-data";
import { ROUTES } from "../../../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../../../lib/surface-state";

type CompletionPageProps = {
  params: Promise<{ programSlug: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function CompletionPage({
  params,
  searchParams,
}: CompletionPageProps) {
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
            retryHref={ROUTES.completion(programSlug)}
            backHref={ROUTES.programLearning(programSlug)}
          />
          {program && isContentVisible(state) ? (
            <>
              <Breadcrumbs
                items={[
                  {
                    label: "Course",
                    href: ROUTES.programLearning(program.slug),
                  },
                  { label: "Completion" },
                ]}
              />
              <PreviewNotice />
              <section
                className="completion-hero"
                aria-labelledby="completion-title"
              >
                <div className="completion-hero__icon">
                  <Award size={24} aria-hidden="true" />
                </div>
                <p className="eyebrow">
                  <span aria-hidden="true" /> Course completion · preview
                </p>
                <h1 id="completion-title">
                  Earn the record.
                  <br />
                  <em>Keep the distinction.</em>
                </h1>
                <p>
                  The connected service will evaluate the published course
                  version, verify the required evidence, and issue a completion
                  certificate idempotently.
                </p>
                <div className="completion-hero__rule">
                  <LockKeyhole size={16} aria-hidden="true" />
                  <span>
                    Not a competency certification. Not a client-side claim.
                  </span>
                </div>
              </section>
              <CompletionChecklist />
              <div className="completion-footer-nav">
                <Link
                  className="text-link"
                  href={ROUTES.programLearning(program.slug)}
                >
                  <ArrowLeft size={15} aria-hidden="true" /> Back to course
                </Link>
                <Link
                  className="text-link"
                  href={ROUTES.certificate("preview-certificate")}
                >
                  Preview certificate view{" "}
                  <Award size={15} aria-hidden="true" />
                </Link>
              </div>
            </>
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
