import { AuthFlowPage } from "../components/auth-flow-page";
import { OnboardingForm } from "../components/onboarding-form";
import { SurfaceStatePanel } from "../components/surface-state";
import { courseIntentHref, parseCourseIntent } from "../lib/course-intent";
import { ROUTES } from "../lib/routes";
import {
  onboardingHref,
  onboardingReturnHref,
  parseOnboardingReturnIntent,
} from "../lib/onboarding-route";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../lib/surface-state";

type OnboardingPageProps = {
  searchParams: Promise<{
    state?: QueryValue;
    return?: QueryValue;
    course?: QueryValue;
  }>;
};

export default async function OnboardingPage({
  searchParams,
}: OnboardingPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);
  const returnIntent = parseOnboardingReturnIntent(query.return);
  const courseIntent = parseCourseIntent(query.course);
  const returnHref = onboardingReturnHref(returnIntent, courseIntent);

  return (
    <AuthFlowPage
      eyebrow="Learning setup"
      heading="Make the course fit your work."
      copy="Answer only what helps. You can skip every step and update these details later."
      backHref={returnHref}
      backLabel={
        returnIntent === "settings"
          ? "Back to settings"
          : "Back to learner home"
      }
      liveProgress
      variant="onboarding"
      steps={[
        { label: "Context", state: "upcoming" },
        { label: "Goal", state: "upcoming" },
        { label: "Optional details", state: "upcoming" },
      ]}
    >
      <SurfaceStatePanel
        state={state}
        retryHref={onboardingHref(returnIntent, courseIntent)}
        signInHref={courseIntentHref(ROUTES.login, courseIntent)}
        backHref={returnHref}
        pageHeadingPresent
      />
      {isContentVisible(state) ? (
        <OnboardingForm returnHref={returnHref} courseIntent={courseIntent} />
      ) : null}
    </AuthFlowPage>
  );
}
