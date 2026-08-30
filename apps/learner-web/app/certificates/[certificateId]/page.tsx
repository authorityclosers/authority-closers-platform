import { LiveCertificate } from "../../components/learner-runtime";
import { LearnerShell } from "../../components/site-shell";
import { SurfaceStatePanel } from "../../components/surface-state";
import { parseSurfaceState, type QueryValue } from "../../lib/surface-state";

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
  const state = parseSurfaceState(query.state);

  return (
    <LearnerShell current="certificate">
      <main id="main-content" className="learner-main">
        <div className="page-container">
          <SurfaceStatePanel
            state={state}
            retryHref={`/certificates/${certificateId}`}
            backHref="/home"
          />
          {state === "DEFAULT" ? (
            <LiveCertificate certificateId={certificateId} />
          ) : null}
        </div>
      </main>
    </LearnerShell>
  );
}
