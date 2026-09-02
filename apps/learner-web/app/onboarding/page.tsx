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
  searchParams: Promise<{ state?: QueryValue; return?: QueryValue }>;
};

export type OnboardingReturnIntent = "home" | "settings";

export function parseOnboardingReturnIntent(
  value: QueryValue,
): OnboardingReturnIntent {
  const candidate = Array.isArray(value) ? value[0] : value;
  return candidate === "settings" ? "settings" : "home";
}

export function onboardingReturnHref(intent: OnboardingReturnIntent): string {
  return intent === "settings" ? ROUTES.settings : ROUTES.learnerHome;
}

export function onboardingHref(intent: OnboardingReturnIntent): string {
  return intent === "settings"
    ? `${ROUTES.onboarding}?return=settings`
    : ROUTES.onboarding;
}

export default async function OnboardingPage({
  searchParams,
}: OnboardingPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);
  const returnIntent = parseOnboardingReturnIntent(query.return);
  const returnHref = onboardingReturnHref(returnIntent);

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
        retryHref={onboardingHref(returnIntent)}
        backHref={returnHref}
        pageHeadingPresent
      />
      {isContentVisible(state) ? (
        <OnboardingForm returnHref={returnHref} />
      ) : null}
    </AuthFlowPage>
  );
}
