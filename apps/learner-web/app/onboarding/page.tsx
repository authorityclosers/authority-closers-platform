import { ArrowLeft, Compass } from "lucide-react";
import Link from "next/link";

import { OnboardingForm } from "../components/onboarding-form";
import { LearnerShell } from "../components/site-shell";
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
    <LearnerShell current="none">
      <main
        id="main-content"
        className="learner-main auth-main clarity-onboarding-main"
      >
        <div className="onboarding-layout clarity-onboarding-layout">
          <section
            className="onboarding-intro clarity-onboarding-intro"
            aria-labelledby="onboarding-title"
          >
            <Link
              className="text-link clarity-onboarding-back"
              href={ROUTES.learnerHome}
            >
              <ArrowLeft size={15} aria-hidden="true" /> Back to learner home
            </Link>
            <p className="eyebrow">
              <span aria-hidden="true" /> Start with context
            </p>
            <h1 id="onboarding-title">Set up your learning profile.</h1>
            <p>
              Save a small amount of context, leave optional details blank, or
              skip and resume later.
            </p>
            <div className="onboarding-signal">
              <Compass size={20} aria-hidden="true" />
              <span>Your saved answers can be updated from Settings.</span>
            </div>
            <ol className="clarity-onboarding-steps" aria-hidden="true">
              <li className="is-active">
                <span>01</span>
                <span>Context</span>
              </li>
              <li>
                <span>02</span>
                <span>Goal</span>
              </li>
              <li>
                <span>03</span>
                <span>First win</span>
              </li>
            </ol>
          </section>
          <section
            className="onboarding-panel clarity-onboarding-panel"
            aria-label="Learner onboarding form"
          >
            <SurfaceStatePanel
              state={state}
              retryHref={ROUTES.onboarding}
              backHref={ROUTES.learnerHome}
              pageHeadingPresent
            />
            {isContentVisible(state) ? <OnboardingForm /> : null}
          </section>
        </div>
      </main>
    </LearnerShell>
  );
}
