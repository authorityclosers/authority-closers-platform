import { AuthFlowPage } from "../components/auth-flow-page";
import { OnboardingForm } from "../components/onboarding-form";
import { SurfaceStatePanel } from "../components/surface-state";
import { parseCourseIntent } from "../lib/course-intent";
import {
  activityIntentHref,
  parseActivityIntent,
} from "../lib/activity-intent";
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
    activity?: QueryValue;
  }>;
};

export default async function OnboardingPage({
  searchParams,
}: OnboardingPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);
  const returnIntent = parseOnboardingReturnIntent(query.return);
  const courseIntent =
    returnIntent === "settings" ? null : parseCourseIntent(query.course);
  const activityIntent =
    returnIntent === "settings" ? null : parseActivityIntent(query.activity);
  const returnHref = onboardingReturnHref(
    returnIntent,
    courseIntent,
    activityIntent,
  );

  return (
    <AuthFlowPage
      eyebrow="Learning setup"
      heading="Make the course fit your work."
      copy="Answer only what helps. You can skip every step and update these details later."
      backHref={returnHref}
      backLabel={
        returnIntent === "settings"
          ? "Back to settings"
          : activityIntent
            ? "Back to activity"
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
        retryHref={onboardingHref(returnIntent, courseIntent, activityIntent)}
        signInHref={activityIntentHref(
          ROUTES.login,
          activityIntent,
          courseIntent,
        )}
        backHref={returnHref}
        pageHeadingPresent
      />
      {isContentVisible(state) ? (
        <OnboardingForm
          returnHref={returnHref}
          courseIntent={courseIntent}
          activityIntent={activityIntent}
        />
      ) : null}
    </AuthFlowPage>
  );
}
