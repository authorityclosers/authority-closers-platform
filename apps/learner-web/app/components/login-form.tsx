"use client";

import { ArrowRight, Eye, EyeOff } from "lucide-react";
import { Button, Field } from "@ac/ui/kit";
import { BrandMark as SalesXrayMark } from "../../../sales-xray-web/app/shell/brand-lockup";
import { ReflexMark } from "../shell/reflex-mark";
import { salesXrayForHost } from "../shell/places";
import {
  createHandoffVerifier,
  handoffChallenge,
  handoffReturnPath,
  HANDOFF_VERIFIER_KEY,
} from "../lib/cross-app-handoff";
import styles from "./reflex-login.module.css";
import Link from "next/link";
import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { googleAuthStartUrl } from "../lib/auth-links";
import { type CourseIntent } from "../lib/course-intent";
import { parseCourseIntent } from "../lib/course-intent";
import {
  activityReturnHref,
  parseActivityIntent,
  type ActivityIntent,
} from "../lib/activity-intent";
import {
  authIntentHref,
  parseSalesAuthNext,
  SALES_XRAY_PATH,
  type SalesAuthNext,
} from "../lib/sales-auth-return";
import {
  ApiError,
  createLearnerApi,
  type OnboardingStatus,
} from "../lib/learner-api";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";

function errorMessage(error: unknown): string {
  return userFacingRequestError(
    error,
    "The request did not finish. Check your connection and try again.",
  );
}

type LoginFormProps = {
  sessionExpired?: boolean;
  handoffExpired?: boolean;
  returnPath?: string;
  stagingBridge?: boolean;
  courseIntent?: CourseIntent;
  activityIntent?: ActivityIntent;
  salesNext?: SalesAuthNext;
};

const STAGING_APP_ORIGIN = "https://staging.authorityclosers.com";
const subscribeHydration = () => () => {};
const clientHydrated = () => true;
const serverHydrated = () => false;

function stagingHref(path: string): string {
  return new URL(path, STAGING_APP_ORIGIN).toString();
}

export function routeAfterOnboarding(
  status?: OnboardingStatus,
  courseIntent: CourseIntent = null,
  activityIntent: ActivityIntent = null,
  salesNext: SalesAuthNext = null,
): string {
  if (status === "completed" || status === "skipped") {
    if (
      parseCourseIntent(courseIntent) ||
      parseActivityIntent(activityIntent)
    ) {
      return activityReturnHref(activityIntent, courseIntent);
    }
    return parseSalesAuthNext(salesNext) ? SALES_XRAY_PATH : ROUTES.learnerHome;
  }
  return authIntentHref(
    ROUTES.onboarding,
    activityIntent,
    courseIntent,
    salesNext,
  );
}

export function LoginForm({
  sessionExpired = false,
  handoffExpired = false,
  returnPath,
  stagingBridge = false,
  courseIntent = null,
  activityIntent = null,
  salesNext = null,
}: LoginFormProps) {
  const Heading = sessionExpired ? "h2" : "h1";
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    clientHydrated,
    serverHydrated,
  );
  const [pending, setPending] = useState(false);
  const [handoffPending, setHandoffPending] = useState(false);
  const [showExpired, setShowExpired] = useState(handoffExpired);
  const handoffLock = useRef(false);
  const salesOrigin = hydrated
    ? salesXrayForHost(window.location.hostname)
    : null;
  const destination = handoffReturnPath(
    returnPath ??
      (activityIntent || courseIntent
        ? activityReturnHref(activityIntent, courseIntent)
        : (salesNext ?? "/home")),
  );
  const [error, setError] = useState<string | null>(null);
  const [verificationRequired, setVerificationRequired] = useState(false);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);
  const authenticateUrl = stagingBridge
    ? stagingHref(
        googleAuthStartUrl(
          "authenticate",
          courseIntent,
          activityIntent,
          salesNext,
        ),
      )
    : googleAuthStartUrl(
        "authenticate",
        courseIntent,
        activityIntent,
        salesNext,
      );
  const registrationHref = authIntentHref(
    ROUTES.register,
    activityIntent,
    courseIntent,
    salesNext,
  );
  const verificationHref = authIntentHref(
    ROUTES.verifyEmail,
    activityIntent,
    courseIntent,
    salesNext,
  );
  const forgotPasswordHref = authIntentHref(
    ROUTES.forgotPassword,
    activityIntent,
    courseIntent,
    salesNext,
  );

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hydrated || pending) return;
    setPending(true);
    setError(null);
    setVerificationRequired(false);
    const values = new FormData(event.currentTarget);
    try {
      const api = createLearnerApi();
      await api.loginPassword(
        String(values.get("email") ?? ""),
        String(values.get("password") ?? ""),
      );
      try {
        const onboarding = await api.onboarding();
        window.location.assign(
          routeAfterOnboarding(
            onboarding.status,
            courseIntent,
            activityIntent,
            salesNext,
          ),
        );
      } catch {
        window.location.assign(
          routeAfterOnboarding(
            undefined,
            courseIntent,
            activityIntent,
            salesNext,
          ),
        );
      }
    } catch (requestError) {
      setError(errorMessage(requestError));
      setVerificationRequired(
        requestError instanceof ApiError &&
          requestError.code === "email_verification_required",
      );
      setPending(false);
    }
  }

  async function continueWithSalesXray() {
    if (!salesOrigin || handoffLock.current) return;
    handoffLock.current = true;
    setHandoffPending(true);
    setError(null);
    try {
      const verifier = createHandoffVerifier();
      sessionStorage.setItem(HANDOFF_VERIFIER_KEY, verifier);
      const challenge = await handoffChallenge(verifier);
      const query = new URLSearchParams({ challenge, return: destination });
      // Sales X-Ray is another site (salesXrayForHost), so this is a full navigation, not a router push.
      window.location.assign(
        new URL(`/connect/reflex?${query}`, salesOrigin).href,
      );
    } catch {
      try {
        sessionStorage.removeItem(HANDOFF_VERIFIER_KEY);
      } catch {
        /* Storage is unavailable. */
      }
      handoffLock.current = false;
      setHandoffPending(false);
      setError("Couldn't open Sales X-Ray. Please try again.");
    }
  }

  return (
    <section className={styles.card} aria-labelledby="reflex-login-title">
      <header>
        <ReflexMark size={40} />
        <Heading id="reflex-login-title">Sign in to Reflex</Heading>
        <p>Sales training by Authority Closers</p>
      </header>
      {stagingBridge ? (
        <p className={styles.staging}>
          Use your verified staging email and password. Account creation,
          recovery, and Google sign-in continue on the deployed staging surface.
        </p>
      ) : null}
      {sessionExpired ? <p role="status">Sign in to continue.</p> : null}
      <div className={styles.options}>
        {salesOrigin ? (
          <Button
            variant="primary"
            onClick={continueWithSalesXray}
            disabled={pending || handoffPending || !hydrated}
          >
            <span className={styles.mark}>
              <SalesXrayMark markOnly />
            </span>
            {handoffPending
              ? "Opening Sales X-Ray…"
              : "Continue with Sales X-Ray"}
          </Button>
        ) : null}
        <a className={styles.google} href={authenticateUrl}>
          {stagingBridge
            ? "Continue with Google on staging"
            : "Continue with Google"}
        </a>
      </div>
      <div className={styles.email}>Email</div>
      <form className={styles.form} method="post" onSubmit={submit}>
        <Field label="Email address">
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="username"
            inputMode="email"
            required
            disabled={pending || !hydrated}
          />
        </Field>
        <Field label="Password">
          <span className={styles.password}>
            <input
              id="login-password"
              name="password"
              type={passwordVisible ? "text" : "password"}
              autoComplete="current-password"
              required
              disabled={pending || !hydrated}
            />
            <button
              type="button"
              aria-label={passwordVisible ? "Hide password" : "Show password"}
              aria-pressed={passwordVisible}
              onClick={() => setPasswordVisible((visible) => !visible)}
              disabled={pending || !hydrated}
            >
              {passwordVisible ? (
                <EyeOff size={18} aria-hidden="true" />
              ) : (
                <Eye size={18} aria-hidden="true" />
              )}
            </button>
          </span>
        </Field>
        {error ? (
          <div role="alert" tabIndex={-1} ref={errorRef}>
            <strong>Sign-in could not be completed</strong>
            <p>{error}</p>
            {verificationRequired ? (
              stagingBridge ? (
                <a href={stagingHref(verificationHref)}>
                  Request on deployed staging
                </a>
              ) : (
                <Link href={verificationHref}>
                  Request a fresh verification link
                </Link>
              )
            ) : null}
          </div>
        ) : null}
        <Button type="submit" disabled={pending || !hydrated}>
          {pending ? "Signing in…" : "Sign in"}
          <ArrowRight size={17} aria-hidden="true" />
        </Button>
        {stagingBridge ? (
          <a href={stagingHref(forgotPasswordHref)}>
            Forgot your password? Continue on staging
          </a>
        ) : (
          <Link href={forgotPasswordHref}>Forgot your password?</Link>
        )}
      </form>
      <div className={styles.footer}>
        <span>First time here?</span>
        {stagingBridge ? (
          <a href={stagingHref(registrationHref)}>Create on deployed staging</a>
        ) : (
          <Link href={registrationHref}>Create your free learner account</Link>
        )}
      </div>
      {showExpired ? (
        <aside
          className={styles.corner}
          role="status"
          aria-label="Sign-in link expired"
        >
          <Button
            variant="ghost"
            aria-label="Dismiss sign-in message"
            onClick={() => setShowExpired(false)}
          >
            Close
          </Button>
          <strong>{"Let's try that again"}</strong>
          <p>This sign-in link has expired. Try again from Sales X-Ray.</p>
        </aside>
      ) : null}
    </section>
  );
}
