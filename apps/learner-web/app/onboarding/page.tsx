import { ArrowLeft, Compass } from "lucide-react";
import Link from "next/link";

import { OnboardingForm } from "../components/onboarding-form";
import { PreviewNotice } from "../components/preview-notice";
import { PublicShell } from "../components/site-shell";
import { SurfaceStatePanel } from "../components/surface-state";
import { ROUTES } from "../lib/routes";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../lib/surface-state";

type OnboardingPageProps = {
  searchParams: Promise<{ state?: QueryValue }>;
};

export default async function OnboardingPage({
  searchParams,
}: OnboardingPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);

  return (
    <PublicShell>
      <main id="main-content" className="auth-main">
        <div className="onboarding-layout">
          <section
            className="onboarding-intro"
            aria-labelledby="onboarding-title"
          >
            <Link className="text-link" href={ROUTES.home}>
              <ArrowLeft size={15} aria-hidden="true" /> Back to published
              programs
            </Link>
            <p className="eyebrow">
              <span aria-hidden="true" /> Start with context
            </p>
            <h1 id="onboarding-title">
              Make the first
              <br />
              <em>rep yours.</em>
            </h1>
            <p>
              This route shows the intended profile fields without collecting or
              applying personal data. The controls remain disabled until
              authenticated profile persistence is connected.
            </p>
            <div className="onboarding-signal">
              <Compass size={20} aria-hidden="true" />
              <span>
                First Win guidance · one useful move in approximately 15 minutes
              </span>
            </div>
          </section>
          <section
            className="onboarding-panel"
            aria-label="Preview onboarding form"
          >
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.onboarding}
              backHref={ROUTES.home}
              pageHeadingPresent
            />
            {isContentVisible(state) ? (
              <>
                <PreviewNotice />
                <OnboardingForm />
              </>
            ) : null}
          </section>
        </div>
      </main>
    </PublicShell>
  );
}
