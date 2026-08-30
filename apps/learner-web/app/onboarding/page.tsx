import { ArrowLeft, Compass } from "lucide-react";
import Link from "next/link";

import { OnboardingForm } from "../components/onboarding-form";
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
              Save a small amount of context, leave optional details blank, or
              skip and resume later. Your answers never become an automated
              score.
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
            aria-label="Learner onboarding form"
          >
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.onboarding}
              backHref={ROUTES.home}
              pageHeadingPresent
            />
            {isContentVisible(state) ? <OnboardingForm /> : null}
          </section>
        </div>
      </main>
    </PublicShell>
  );
}
