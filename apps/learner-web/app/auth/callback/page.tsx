import {
  ArrowRight,
  CircleAlert,
  RefreshCw,
  ShieldCheck,
  UserPlus,
} from "lucide-react";
import Link from "next/link";

import { AuthFlowPage } from "../../components/auth-flow-page";
import { SurfaceStatePanel } from "../../components/surface-state";
import { ROUTES } from "../../lib/routes";
import { parseCourseIntent } from "../../lib/course-intent";
import {
  activityIntentHref,
  parseActivityIntent,
} from "../../lib/activity-intent";
import {
  isContentVisible,
  parseSurfaceState,
  type QueryValue,
} from "../../lib/surface-state";

type CallbackPageProps = {
  searchParams: Promise<{
    result?: QueryValue;
    state?: QueryValue;
    course?: QueryValue;
    activity?: QueryValue;
  }>;
};

type CallbackResult =
  | "consent_required"
  | "consent_update_required"
  | "provider_rejected"
  | "provider_unavailable"
  | "registration_required";

const callbackResults: Record<
  CallbackResult,
  {
    eyebrow: string;
    title: string;
    detail: string;
    actionHref: string;
    actionLabel: string;
    icon: typeof ShieldCheck;
  }
> = {
  consent_required: {
    eyebrow: "One consent step remains",
    title: "Confirm your learner access.",
    detail:
      "Your Google identity is recognized. Confirm that you are 18 or older and accept the current Terms and Privacy notice before we open the course.",
    actionHref: ROUTES.register,
    actionLabel: "Review and continue",
    icon: ShieldCheck,
  },
  consent_update_required: {
    eyebrow: "Account review required",
    title: "Your consent record needs an update.",
    detail:
      "We kept your existing identity and learning data unchanged. Contact Authority Closers support so the reviewed consent update can be completed safely.",
    actionHref:
      "mailto:admin@authorityclosers.com?subject=Authority%20Closers%20learner%20consent%20update",
    actionLabel: "Contact support",
    icon: CircleAlert,
  },
  provider_rejected: {
    eyebrow: "Google sign-in stopped",
    title: "Google could not confirm this attempt.",
    detail:
      "No learner session was created. Return to sign in and try again, or use your verified email and password.",
    actionHref: ROUTES.login,
    actionLabel: "Return to sign in",
    icon: RefreshCw,
  },
  provider_unavailable: {
    eyebrow: "Temporary provider issue",
    title: "Google sign-in is unavailable right now.",
    detail:
      "Your account was not changed. Try again shortly, or use your verified email and password while Google recovers.",
    actionHref: ROUTES.login,
    actionLabel: "Return to sign in",
    icon: RefreshCw,
  },
  registration_required: {
    eyebrow: "Create your learner identity",
    title: "This Google account is not linked yet.",
    detail:
      "Create your free learner account, confirm the required consent, and continue with the same Google account. We will not create an account silently from sign in. If you already use a verified email and password here, sign in with those credentials; you can connect Google later from account settings.",
    actionHref: ROUTES.register,
    actionLabel: "Create free account",
    icon: UserPlus,
  },
};

function parseCallbackResult(value: QueryValue): CallbackResult | null {
  const candidate = Array.isArray(value) ? value[0] : value;
  return candidate &&
    Object.prototype.hasOwnProperty.call(callbackResults, candidate)
    ? (candidate as CallbackResult)
    : null;
}

export default async function CallbackPage({
  searchParams,
}: CallbackPageProps) {
  const query = await searchParams;
  const state = parseSurfaceState(query.state);
  const result = parseCallbackResult(query.result);
  const courseIntent = parseCourseIntent(query.course);
  const activityIntent = parseActivityIntent(query.activity);
  const loginHref = activityIntentHref(
    ROUTES.login,
    activityIntent,
    courseIntent,
  );
  const recovery = result ? callbackResults[result] : null;
  const recoveryHref =
    recovery?.actionHref === ROUTES.login ||
    recovery?.actionHref === ROUTES.register
      ? activityIntentHref(recovery.actionHref, activityIntent, courseIntent)
      : recovery?.actionHref;
  const retryParameters = new URLSearchParams();
  if (result) retryParameters.set("result", result);
  if (courseIntent) retryParameters.set("course", courseIntent);
  if (activityIntent) retryParameters.set("activity", activityIntent);
  const retryHref = `${ROUTES.callback}${retryParameters.size ? `?${retryParameters}` : ""}`;
  const RecoveryIcon = recovery?.icon ?? ShieldCheck;

  return (
    <AuthFlowPage
      eyebrow="Google sign-in"
      heading="We need one more step."
      copy="Complete the bounded account step below, then start a fresh sign-in attempt."
      backHref={loginHref}
      backLabel="Back to sign in"
      steps={[
        { label: "Identity", state: "outline", detail: "Account task" },
        {
          label: "Account check",
          state: "outline",
          detail: "Result shown here",
        },
        { label: "Start learning", state: "outline", detail: "After access" },
      ]}
    >
      <section
        className="auth-card clarity-auth-card callback-card"
        aria-labelledby="callback-title"
      >
        <div className="callback-card__icon">
          <RecoveryIcon size={22} aria-hidden="true" />
        </div>
        <p className="eyebrow">
          <span aria-hidden="true" />
          {recovery?.eyebrow ?? "Secure callback boundary"}
        </p>
        <h2 id="callback-title">
          {recovery?.title ?? "Sign-in result unavailable."}
        </h2>
        {state !== "DEFAULT" ? (
          <SurfaceStatePanel
            state={state}
            retryHref={retryHref}
            signInHref={loginHref}
            backHref={loginHref}
            pageHeadingPresent
          />
        ) : null}
        {isContentVisible(state) && recovery ? (
          <>
            <p className="callback-card__intro">{recovery.detail}</p>
            <Link
              className="button button--ink button--full"
              href={recoveryHref!}
            >
              {recovery.actionLabel}
              <ArrowRight size={17} aria-hidden="true" />
            </Link>
            {result === "registration_required" ? (
              <Link
                className="button button--outline button--full"
                href={loginHref}
              >
                Sign in with password
              </Link>
            ) : null}
            <div className="boundary-card" role="note">
              <strong>Your account remains protected</strong>
              <span>
                A session is created only after Google, identity, consent, and
                learner-access checks all pass.
              </span>
            </div>
          </>
        ) : isContentVisible(state) ? (
          <>
            <p className="callback-card__intro">
              This page only accepts a server-issued sign-in result. Return to
              sign in to start a fresh, protected Google transaction.
            </p>
            <Link className="button button--ink button--full" href={loginHref}>
              Return to sign in
              <ArrowRight size={17} aria-hidden="true" />
            </Link>
          </>
        ) : null}
      </section>
    </AuthFlowPage>
  );
}
