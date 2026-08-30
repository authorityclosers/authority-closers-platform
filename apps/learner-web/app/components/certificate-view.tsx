import { ArrowLeft, Download, ShieldCheck } from "lucide-react";

import type { CertificateViewModel } from "../lib/view-models";

export function CertificateView({
  certificate,
}: {
  certificate: CertificateViewModel;
}) {
  return (
    <div className="certificate-layout">
      <article className="certificate-card" aria-labelledby="certificate-title">
        <div className="certificate-card__watermark" aria-hidden="true">
          PREVIEW
        </div>
        <div className="certificate-card__topline">
          <span className="certificate-card__mark">
            <ShieldCheck size={18} aria-hidden="true" />
          </span>
          <span>Authority Closers · course record</span>
        </div>
        <div className="certificate-card__content">
          <p className="kicker">
            {certificate.certificateStatus.replaceAll("_", " ")}
          </p>
          <h2 id="certificate-title">
            Certificate of
            <br />
            <em>course completion</em>
          </h2>
          <p className="certificate-card__statement">
            This preview would name the learner who completed the published
            course version.
          </p>
          <p className="certificate-card__name">{certificate.learnerName}</p>
          <p className="certificate-card__program">
            {certificate.programTitle}
          </p>
        </div>
        <div className="certificate-card__footer">
          <span>{certificate.issuedLabel}</span>
          <span>Certificate ID · {certificate.id}</span>
        </div>
      </article>
      <aside className="certificate-aside">
        <div className="certificate-aside__icon">
          <ShieldCheck size={20} aria-hidden="true" />
        </div>
        <p className="kicker">Important distinction</p>
        <h2>Completion is not certification.</h2>
        <p>
          {certificate.distinction} This screen is a visual preview, not an
          issued credential or proof of skill.
        </p>
        <div className="certificate-actions">
          <button
            className="button button--outline button--full"
            type="button"
            disabled
          >
            <Download size={16} aria-hidden="true" /> Download when issued
          </button>
          <span className="text-link" aria-disabled="true">
            <ArrowLeft size={15} aria-hidden="true" /> Return when an enrollment
            is available
          </span>
        </div>
      </aside>
    </div>
  );
}
