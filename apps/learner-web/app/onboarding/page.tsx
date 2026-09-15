import { AuthFlowPage } from "../components/auth-flow-page";
import { OnboardingForm } from "../components/onboarding-form";
import { SurfaceStatePanel } from "../components/surface-state";
import { parseCourseIntent } from "../lib/course-intent";
import { parseActivityIntent } from "../lib/activity-intent";
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
import { authIntentHref, parseSalesAuthNext } from "../lib/sales-auth-return";

type OnboardingPageProps = {
  searchParams: Promise<{
    state?: QueryValue;
    return?: QueryValue;
    course?: QueryValue;
    activity?: QueryValue;
    next?: QueryValue;
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
  const salesNext =
    returnIntent === "settings" ? null : parseSalesAuthNext(query.next);
  const salesOnly = Boolean(salesNext && !courseIntent && !activityIntent);
  const returnHref = onboardingReturnHref(
    returnIntent,
    courseIntent,
    activityIntent,
    salesNext,
  );

  return (
    <AuthFlowPage
      eyebrow="Learning setup"
      heading={
        salesOnly ? "Set up your account." : "Make the course fit your work."
      }
      copy="Answer only what helps. You can skip every step and update these details later."
      backHref={returnHref}
      backLabel={
        returnIntent === "settings"
          ? "Back to settings"
          : activityIntent
            ? "Back to activity"
            : salesOnly
              ? "Back to Sales Xray"
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
        retryHref={onboardingHref(
          returnIntent,
          courseIntent,
          activityIntent,
          salesNext,
        )}
        signInHref={authIntentHref(
          ROUTES.login,
          activityIntent,
          courseIntent,
          salesNext,
        )}
        backHref={returnHref}
        pageHeadingPresent
      />
      {isContentVisible(state) ? (
        <OnboardingForm
          returnHref={returnHref}
          courseIntent={courseIntent}
          activityIntent={activityIntent}
          salesNext={salesNext}
        />
      ) : null}
    </AuthFlowPage>
  );
}
