"use client";

import { ArrowRight, Eye, EyeOff, ShieldCheck } from "lucide-react";
import Link from "next/link";
import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { googleAuthStartUrl } from "../lib/auth-links";
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
  stagingBridge?: boolean;
};

const STAGING_APP_ORIGIN = "https://staging.authorityclosers.com";
const subscribeHydration = () => () => {};
const clientHydrated = () => true;
const serverHydrated = () => false;

function stagingHref(path: string): string {
  return new URL(path, STAGING_APP_ORIGIN).toString();
}

export function routeAfterOnboarding(status?: OnboardingStatus): string {
  return status === "completed" || status === "skipped"
    ? ROUTES.learnerHome
    : ROUTES.onboarding;
}

export function LoginForm({
  sessionExpired = false,
  stagingBridge = false,
}: LoginFormProps) {
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    clientHydrated,
    serverHydrated,
  );
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verificationRequired, setVerificationRequired] = useState(false);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);
  const authenticateUrl = stagingBridge
    ? stagingHref(googleAuthStartUrl("authenticate"))
    : googleAuthStartUrl("authenticate");

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
        window.location.assign(routeAfterOnboarding(onboarding.status));
      } catch {
        window.location.assign(routeAfterOnboarding());
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

  return (
    <div className="auth-card clarity-auth-card">
      <div className="auth-card__topline">
        <span className="auth-card__icon">
          <ShieldCheck size={18} aria-hidden="true" />
        </span>
        <span>
          {sessionExpired ? "Session recovery" : "Secure learner access"}
        </span>
      </div>
      <h2>{sessionExpired ? "Sign in to continue." : "Welcome back."}</h2>
      <p className="auth-card__intro">
        {stagingBridge
          ? "Use your verified staging email and password. Account creation, recovery, and Google sign-in continue on the deployed staging surface."
          : "Use your verified email and password, or continue with Google."}
      </p>
      {sessionExpired ? (
        <div className="auth-notice" role="status">
          <ShieldCheck size={18} aria-hidden="true" />
          <span>
            We will re-check your access before returning to the learner
            workspace.
          </span>
        </div>
      ) : null}
      <form className="stack-form" method="post" onSubmit={submit}>
        <div className="field-group">
          <label htmlFor="login-email">Email address</label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="username"
            inputMode="email"
            required
            disabled={pending || !hydrated}
          />
        </div>
        <div className="field-group">
          <label htmlFor="login-password">Password</label>
          <div className="auth-password-field">
            <input
              id="login-password"
              name="password"
              type={passwordVisible ? "text" : "password"}
              autoComplete="current-password"
              required
              disabled={pending || !hydrated}
            />
            <button
              className="auth-password-toggle"
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
          </div>
        </div>
        {error ? (
          <div
            className="auth-error-summary"
            role="alert"
            tabIndex={-1}
            ref={errorRef}
          >
            <strong>Sign-in could not be completed</strong>
            <p>{error}</p>
            {verificationRequired ? (
              stagingBridge ? (
                <a className="text-link" href={stagingHref(ROUTES.verifyEmail)}>
                  Request on deployed staging
                </a>
              ) : (
                <Link className="text-link" href={ROUTES.verifyEmail}>
                  Request a fresh verification link
                </Link>
              )
            ) : null}
          </div>
        ) : null}
        <button
          className="button button--ink button--full"
          disabled={pending || !hydrated}
        >
          {pending ? "Signing in…" : "Sign in"}
          <ArrowRight size={17} aria-hidden="true" />
        </button>
        {stagingBridge ? (
          <a className="text-link" href={stagingHref(ROUTES.forgotPassword)}>
            Forgot your password? Continue on staging
          </a>
        ) : (
          <Link className="text-link" href={ROUTES.forgotPassword}>
            Forgot your password?
          </Link>
        )}
      </form>
      <div className="auth-divider" aria-hidden="true">
        <span>or</span>
      </div>
      <a className="button button--outline button--full" href={authenticateUrl}>
        {stagingBridge
          ? "Continue with Google on staging"
          : "Continue with Google"}
      </a>
      <div className="auth-card__footer">
        <span>First time here—including with Google?</span>
        {stagingBridge ? (
          <a href={stagingHref(ROUTES.register)}>Create on deployed staging</a>
        ) : (
          <Link href={ROUTES.register}>Create your free learner account</Link>
        )}
      </div>
    </div>
  );
}
