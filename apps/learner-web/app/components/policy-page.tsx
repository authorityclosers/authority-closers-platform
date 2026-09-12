import { ArrowLeft, CheckCircle2, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { ROUTES } from "../lib/routes";
import {
  LEARNER_POLICY_CONTACT,
  LEARNER_POLICY_VERSION,
} from "../lib/learner-policy";
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
      <main id="main-content" className="public-main policy-page" tabIndex={-1}>
        <div className="page-container">
          <Link className="text-link policy-page__back" href={ROUTES.home}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to the course
            catalog
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
              <p>Published service policy</p>
              <strong>{LEARNER_POLICY_VERSION}</strong>
              <span>Effective {effectiveDate}</span>
            </aside>
          </header>

          <div className="policy-layout">
            <aside className="policy-boundary">
              <p className="kicker">Your learning account</p>
              <h2>Free course. Clear choices.</h2>
              <p>
                Read these policies before creating an account. Keep the version
                and contact details here for questions about your access or
                data.
              </p>
              <div>
                <CheckCircle2 size={17} aria-hidden="true" />
                Explicit enrollment in the Free Course
              </div>
              <div>
                <CheckCircle2 size={17} aria-hidden="true" />
                Optional profile and academy leaderboard choices
              </div>
              <div>
                <CheckCircle2 size={17} aria-hidden="true" />
                Privacy requests through the published contact
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
            <h2>Contact Authority Closers.</h2>
            <a href={`mailto:${LEARNER_POLICY_CONTACT}`}>
              {LEARNER_POLICY_CONTACT}
            </a>
          </footer>
        </div>
      </main>
    </PublicShell>
  );
}
