import { AuthFlowPage } from "../components/auth-flow-page";
import { OnboardingForm } from "../components/onboarding-form";
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
    <AuthFlowPage
      eyebrow="Learning setup"
      heading="Make the course fit your work."
      copy="Answer only what helps. You can skip every step and update these details later."
      backHref={ROUTES.learnerHome}
      backLabel="Back to learner home"
      variant="onboarding"
      steps={[
        { label: "Context", state: "outline", detail: "Optional" },
        { label: "Goal", state: "outline", detail: "Optional" },
        { label: "First win", state: "outline", detail: "Optional" },
      ]}
    >
      <SurfaceStatePanel
        state={state}
        retryHref={ROUTES.onboarding}
        backHref={ROUTES.learnerHome}
        pageHeadingPresent
      />
      {isContentVisible(state) ? <OnboardingForm /> : null}
    </AuthFlowPage>
  );
}
