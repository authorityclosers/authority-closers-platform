import { ArrowLeft, BadgeCheck } from "lucide-react";
import Link from "next/link";

import { CertificateView } from "../../components/certificate-view";
import { PreviewNotice } from "../../components/preview-notice";
import { Breadcrumbs, LearnerShell } from "../../components/site-shell";
import { SurfaceStatePanel } from "../../components/surface-state";
import { demoCertificate } from "../../lib/course-data";
import { ROUTES } from "../../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../../lib/surface-state";

type CertificatePageProps = {
  params: Promise<{ certificateId: string }>;
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function CertificatePage({
  params,
  searchParams,
}: CertificatePageProps) {
  const { certificateId } = await params;
  const query = await searchParams;
  const certificate =
    certificateId === demoCertificate.id ? demoCertificate : undefined;
  const state = certificate ? parseSurfaceState(query.state) : "EMPTY";

  return (
    <LearnerShell current="certificate">
      <main id="main-content" className="learner-main">
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={ROUTES.certificate(certificateId)}
            backHref={ROUTES.completion("free-course")}
          />
          {certificate && isContentVisible(state) ? (
            <>
              <Breadcrumbs items={[{ label: "Certificate" }]} />
              <PreviewNotice />
              <section
                className="certificate-hero"
                aria-labelledby="certificate-page-title"
              >
                <div>
                  <Link
                    className="text-link"
                    href={ROUTES.completion("free-course")}
                  >
                    <ArrowLeft size={15} aria-hidden="true" /> Back to
                    completion
                  </Link>
                  <p className="eyebrow">
                    <span aria-hidden="true" /> Learner record preview
                  </p>
                  <h1 id="certificate-page-title">
                    A clear record
                    <br />
                    <em>when the work is done.</em>
                  </h1>
                  <p>
                    The certificate surface is intentionally honest about its
                    status. It becomes a durable record only after the
                    server-authoritative completion predicate passes.
                  </p>
                </div>
                <div className="certificate-hero__badge">
                  <BadgeCheck size={24} aria-hidden="true" />
                  <span>Not issued</span>
                </div>
              </section>
              <CertificateView certificate={certificate} />
            </>
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
