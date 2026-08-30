import { ArrowLeft, CheckCircle2, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { ROUTES } from "../lib/routes";
import { PublicShell } from "./site-shell";

type PolicySection = {
  heading: string;
  body: React.ReactNode;
};

export function PolicyPage({
  eyebrow,
  title,
  summary,
  effectiveDate,
  sections,
}: {
  eyebrow: string;
  title: string;
  summary: string;
  effectiveDate: string;
  sections: PolicySection[];
}) {
  return (
    <PublicShell>
      <main id="main-content" className="public-main policy-page">
        <div className="page-container">
          <Link className="text-link policy-page__back" href={ROUTES.home}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to the public
            preview
          </Link>

          <header className="policy-hero">
            <div>
              <p className="eyebrow">
                <span aria-hidden="true" /> {eyebrow}
              </p>
              <h1>{title}</h1>
              <p className="policy-hero__summary">{summary}</p>
            </div>
            <aside className="policy-hero__status" aria-label="Document status">
              <ShieldCheck size={24} aria-hidden="true" />
              <p>Staging test document</p>
              <strong>Not final production legal terms</strong>
              <span>Effective {effectiveDate}</span>
            </aside>
          </header>

          <div className="policy-layout">
            <aside className="policy-boundary">
              <p className="kicker">Current boundary</p>
              <h2>Invitation-only testing.</h2>
              <p>
                This notice covers the Authority Closers staging environment
                while Google sign-in and the first learning slice are tested.
              </p>
              <div>
                <CheckCircle2 size={17} aria-hidden="true" />
                No paid course or commercial checkout
              </div>
              <div>
                <CheckCircle2 size={17} aria-hidden="true" />
                No call recording, voice analysis, or autonomous scoring
              </div>
              <div>
                <CheckCircle2 size={17} aria-hidden="true" />
                No production learner promise is made by this preview
              </div>
            </aside>

            <article className="policy-copy">
              {sections.map((section, index) => (
                <section key={section.heading}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <h2>{section.heading}</h2>
                    {section.body}
                  </div>
                </section>
              ))}
            </article>
          </div>

          <footer className="policy-contact">
            <p className="kicker">Questions or access requests</p>
            <h2>Use the accountable company channel.</h2>
            <a href="mailto:admin@authorityclosers.com">
              admin@authorityclosers.com
            </a>
          </footer>
        </div>
      </main>
    </PublicShell>
  );
}
