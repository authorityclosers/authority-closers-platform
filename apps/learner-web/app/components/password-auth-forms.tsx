"use client";

import {
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  MailCheck,
} from "lucide-react";
import Link from "next/link";
import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { googleAuthReturnPath, googleAuthStartUrl } from "../lib/auth-links";
import { type CourseIntent } from "../lib/course-intent";
import {
  activityIntentHref,
  type ActivityIntent,
} from "../lib/activity-intent";
import { createLearnerApi } from "../lib/learner-api";
import { ROUTES } from "../lib/routes";
import {
  LEARNER_CONSENT_COPY,
  LEARNER_POLICY_VERSION,
} from "../lib/learner-policy";
import { userFacingRequestError } from "../lib/user-facing-error";

function requestErrorMessage(error: unknown): string {
  return userFacingRequestError(
    error,
    "The request did not finish. Check your connection and try again.",
  );
}

function fragmentToken(): string | null {
  const parameters = new URLSearchParams(window.location.hash.slice(1));
  const token = parameters.get("token");
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}`,
  );
  return token;
}

const subscribeRegistrationHydration = () => () => {};
const registrationClientHydrated = () => true;
const registrationServerHydrated = () => false;

export function RegistrationForm({
  courseIntent = null,
  activityIntent = null,
}: {
  courseIntent?: CourseIntent;
  activityIntent?: ActivityIntent;
}) {
  const hydrated = useSyncExternalStore(
    subscribeRegistrationHydration,
    registrationClientHydrated,
    registrationServerHydrated,
  );
  const loginHref = activityIntentHref(
    ROUTES.login,
    activityIntent,
    courseIntent,
  );
  const [pending, setPending] = useState(false);
  const [complete, setComplete] = useState(false);
  const [consentGranted, setConsentGranted] = useState(false);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hydrated || pending || !consentGranted) return;
    setPending(true);
    setError(null);
    const values = new FormData(event.currentTarget);
    try {
      await createLearnerApi().registerPassword({
        firstName: String(values.get("firstName") ?? ""),
        email: String(values.get("email") ?? ""),
        whatsappNumber: String(values.get("whatsappNumber") ?? ""),
        password: String(values.get("password") ?? ""),
        consent: true,
      });
      setComplete(true);
    } catch (requestError) {
      setError(requestErrorMessage(requestError));
    } finally {
      setPending(false);
    }
  }

  if (complete) {
    return (
      <div className="auth-card clarity-auth-card auth-result" role="status">
        <MailCheck size={34} aria-hidden="true" />
        <h2>Check your inbox.</h2>
        <p>
          If that address can be registered, a verification link is on its way.
          The link expires after 24 hours.
        </p>
        <Link className="button button--outline button--full" href={loginHref}>
          Return to sign in
        </Link>
        <Link className="text-link" href={ROUTES.verifyEmail}>
          Need a fresh verification link?
        </Link>
      </div>
    );
  }

  return (
    <div className="auth-card clarity-auth-card">
      <div className="auth-card__topline">
        <span className="auth-card__icon">
          <KeyRound size={18} aria-hidden="true" />
        </span>
        <span>Free learner account</span>
      </div>
      <h2>Account details.</h2>
      <p className="auth-card__intro">
        Start the free course and keep progress, reflections, and recovery tied
        to one verified identity.
      </p>
      <form className="stack-form" method="post" onSubmit={submit}>
        <fieldset className="auth-fieldset">
          <legend>Identity</legend>
          <div className="field-group">
            <label htmlFor="register-first-name">First name</label>
            <input
              id="register-first-name"
              name="firstName"
              autoComplete="given-name"
              placeholder="First name"
              required
              maxLength={120}
              disabled={pending || !hydrated}
            />
          </div>
          <div className="field-group">
            <label htmlFor="register-email">Email address</label>
            <input
              id="register-email"
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              placeholder="you@example.com"
              required
              maxLength={320}
              disabled={pending || !hydrated}
            />
          </div>
          <div className="field-group">
            <label htmlFor="register-whatsapp">WhatsApp number</label>
            <input
              id="register-whatsapp"
              name="whatsappNumber"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              placeholder="Country code and number"
              required
              minLength={7}
              maxLength={32}
              aria-describedby="register-whatsapp-help"
              disabled={pending || !hydrated}
            />
            <p id="register-whatsapp-help" className="field-help">
              Stored with your learner profile. This number is not used for
              course messages.
            </p>
          </div>
        </fieldset>
        <fieldset className="auth-fieldset">
          <legend>Security</legend>
          <div className="field-group">
            <label htmlFor="register-password">Password</label>
            <div className="auth-password-field">
              <input
                id="register-password"
                name="password"
                type={passwordVisible ? "text" : "password"}
                autoComplete="new-password"
                placeholder="At least 12 characters"
                required
                minLength={12}
                maxLength={256}
                aria-describedby="register-password-help"
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
            <p id="register-password-help" className="field-help">
              Use at least 12 characters. Paste, autofill, and password managers
              are supported.
            </p>
          </div>
        </fieldset>
        <label className="consent-check">
          <input
            name="consent"
            type="checkbox"
            required
            disabled={pending || !hydrated}
            checked={consentGranted}
            onChange={(event) => setConsentGranted(event.currentTarget.checked)}
          />
          <span>
            {LEARNER_CONSENT_COPY.beforeTerms}
            <Link href={ROUTES.terms}>Terms</Link>
            {LEARNER_CONSENT_COPY.beforePrivacy}
            <Link href={ROUTES.privacy}>Privacy notice</Link>
            {LEARNER_CONSENT_COPY.afterPrivacy}
          </span>
        </label>
        {error ? (
          <div
            className="auth-error-summary"
            role="alert"
            tabIndex={-1}
            ref={errorRef}
          >
            <strong>Account creation could not be completed</strong>
            <p>{error}</p>
          </div>
        ) : null}
        <button
          className="button button--ink button--full"
          disabled={pending || !hydrated}
        >
          {pending ? "Creating account…" : "Create free account"}
          <ArrowRight size={17} aria-hidden="true" />
        </button>
      </form>
      <div className="auth-divider" aria-hidden="true">
        <span>or</span>
      </div>
      <form
        className="stack-form"
        action={googleAuthStartUrl("register", courseIntent, activityIntent)}
        method="get"
      >
        <input type="hidden" name="action" value="register" />
        <input type="hidden" name="surface" value="learner" />
        <input
          type="hidden"
          name="return_path"
          value={googleAuthReturnPath("register", courseIntent, activityIntent)}
        />
        <input
          type="hidden"
          name="consent"
          value="true"
          disabled={!hydrated || !consentGranted}
        />
        <input
          type="hidden"
          name="consent_version"
          value={LEARNER_POLICY_VERSION}
          disabled={!hydrated || !consentGranted}
        />
        <button
          className="button button--outline button--full"
          type="submit"
          disabled={!hydrated || !consentGranted || pending}
        >
          Continue with Google
          <ArrowRight size={17} aria-hidden="true" />
        </button>
      </form>
      <div className="auth-card__footer">
        <span>Already verified?</span>
        <Link href={loginHref}>Sign in</Link>
      </div>
    </div>
  );
}

export function RecoveryRequestForm() {
  const hydrated = useSyncExternalStore(
    subscribeRegistrationHydration,
    registrationClientHydrated,
    registrationServerHydrated,
  );
  const [pending, setPending] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hydrated || pending) return;
    setPending(true);
    setError(null);
    const values = new FormData(event.currentTarget);
    try {
      await createLearnerApi().requestPasswordRecovery(
        String(values.get("email") ?? ""),
      );
      setComplete(true);
    } catch (requestError) {
      setError(requestErrorMessage(requestError));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="auth-card clarity-auth-card">
      <div className="auth-card__topline">
        <span className="auth-card__icon">
          <KeyRound size={18} aria-hidden="true" />
        </span>
        <span>Account recovery</span>
      </div>
      <h2>{complete ? "Check your inbox." : "Request a reset link."}</h2>
      {complete ? (
        <div className="auth-result" role="status">
          <p>
            If the address belongs to an active account, a 30-minute reset link
            is on its way.
          </p>
          <Link
            className="button button--outline button--full"
            href={ROUTES.login}
          >
            Return to sign in
          </Link>
        </div>
      ) : (
        <form className="stack-form" method="post" onSubmit={submit}>
          <p className="auth-card__intro">
            Enter the email used for your learner account. The response is
            intentionally the same for every address.
          </p>
          <div className="field-group">
            <label htmlFor="recovery-email">Email address</label>
            <input
              id="recovery-email"
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              required
              disabled={pending || !hydrated}
            />
          </div>
          {error ? (
            <div
              className="auth-error-summary"
              role="alert"
              tabIndex={-1}
              ref={errorRef}
            >
              <strong>Recovery request could not be completed</strong>
              <p>{error}</p>
            </div>
          ) : null}
          <button
            className="button button--ink button--full"
            disabled={pending || !hydrated}
          >
            {pending ? "Requesting…" : "Send recovery link"}
          </button>
        </form>
      )}
    </div>
  );
}

export function VerifyEmailFlow() {
  const started = useRef(false);
  const [state, setState] = useState<"working" | "success" | "error">(
    "working",
  );
  const [message, setMessage] = useState("Verifying your email…");
  const [resendPending, setResendPending] = useState(false);
  const [resendComplete, setResendComplete] = useState(false);
  const [resendError, setResendError] = useState<string | null>(null);

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setResendPending(true);
    setResendError(null);
    const values = new FormData(event.currentTarget);
    try {
      await createLearnerApi().resendPasswordVerification(
        String(values.get("email") ?? ""),
      );
      setResendComplete(true);
    } catch (requestError) {
      setResendError(requestErrorMessage(requestError));
    } finally {
      setResendPending(false);
    }
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const token = fragmentToken();
    if (!token) {
      queueMicrotask(() => {
        setState("error");
        setMessage("This verification link is missing its one-time token.");
      });
      return;
    }
    void createLearnerApi()
      .verifyPasswordEmail(token)
      .then(
        () => {
          setState("success");
          setMessage(
            "Your email is verified and your secure session is ready.",
          );
        },
        (error: unknown) => {
          setState("error");
          setMessage(requestErrorMessage(error));
        },
      );
  }, []);

  return (
    <div
      className="auth-card clarity-auth-card auth-result"
      role={state === "error" ? "alert" : "status"}
    >
      {state === "success" ? (
        <CheckCircle2 size={34} aria-hidden="true" />
      ) : (
        <MailCheck size={34} aria-hidden="true" />
      )}
      <h2>
        {state === "working"
          ? "One moment."
          : state === "success"
            ? "Email verified."
            : "Link unavailable."}
      </h2>
      <p>{message}</p>
      {state === "success" ? (
        <Link
          className="button button--ink button--full"
          href={ROUTES.onboarding}
        >
          Continue to onboarding
        </Link>
      ) : null}
      {state === "error" ? (
        <>
          {resendComplete ? (
            <p className="form-message" role="status">
              If the address has an unverified password account, a fresh link is
              on its way.
            </p>
          ) : (
            <form className="stack-form" onSubmit={resend}>
              <div className="field-group">
                <label htmlFor="verification-resend-email">Account email</label>
                <input
                  id="verification-resend-email"
                  name="email"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  required
                  disabled={resendPending}
                />
              </div>
              {resendError ? (
                <p className="form-message form-message--error" role="alert">
                  {resendError}
                </p>
              ) : null}
              <button
                className="button button--ink button--full"
                disabled={resendPending}
              >
                {resendPending ? "Requesting…" : "Send a fresh link"}
              </button>
            </form>
          )}
          <Link
            className="button button--outline button--full"
            href={ROUTES.login}
          >
            Return to sign in
          </Link>
        </>
      ) : null}
    </div>
  );
}

export function PasswordResetForm() {
  const tokenRead = useRef(false);
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [pending, setPending] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (tokenRead.current) return;
    tokenRead.current = true;
    const value = fragmentToken();
    queueMicrotask(() => setToken(value));
  }, []);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    setPending(true);
    setError(null);
    const values = new FormData(event.currentTarget);
    const password = String(values.get("password") ?? "");
    if (password !== String(values.get("passwordConfirm") ?? "")) {
      setError("The passwords do not match.");
      setPending(false);
      return;
    }
    try {
      await createLearnerApi().resetPassword(token, password);
      setComplete(true);
    } catch (requestError) {
      setError(requestErrorMessage(requestError));
    } finally {
      setPending(false);
    }
  }

  if (token === undefined) {
    return (
      <div className="auth-card clarity-auth-card auth-result" role="status">
        <p>Reading the secure reset link…</p>
      </div>
    );
  }
  if (!token) {
    return (
      <div className="auth-card clarity-auth-card auth-result" role="alert">
        <h2>Link unavailable.</h2>
        <p>This reset link is missing its one-time token.</p>
        <Link
          className="button button--outline button--full"
          href={ROUTES.forgotPassword}
        >
          Request another link
        </Link>
      </div>
    );
  }
  if (complete) {
    return (
      <div className="auth-card clarity-auth-card auth-result" role="status">
        <CheckCircle2 size={34} aria-hidden="true" />
        <h2>Password updated.</h2>
        <p>
          All earlier sessions were revoked. Sign in again with your new
          password.
        </p>
        <Link className="button button--ink button--full" href={ROUTES.login}>
          Sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="auth-card clarity-auth-card">
      <div className="auth-card__topline">
        <span className="auth-card__icon">
          <KeyRound size={18} aria-hidden="true" />
        </span>
        <span>Secure reset</span>
      </div>
      <h2>Set your new password.</h2>
      <form className="stack-form" onSubmit={submit}>
        <div className="field-group">
          <label htmlFor="reset-password">New password</label>
          <div className="auth-password-field">
            <input
              id="reset-password"
              name="password"
              type={passwordVisible ? "text" : "password"}
              autoComplete="new-password"
              required
              minLength={12}
              maxLength={256}
              disabled={pending}
            />
            <button
              className="auth-password-toggle"
              type="button"
              aria-label={passwordVisible ? "Hide passwords" : "Show passwords"}
              aria-pressed={passwordVisible}
              onClick={() => setPasswordVisible((visible) => !visible)}
              disabled={pending}
            >
              {passwordVisible ? (
                <EyeOff size={18} aria-hidden="true" />
              ) : (
                <Eye size={18} aria-hidden="true" />
              )}
            </button>
          </div>
        </div>
        <div className="field-group">
          <label htmlFor="reset-password-confirm">Confirm new password</label>
          <div className="auth-password-field">
            <input
              id="reset-password-confirm"
              name="passwordConfirm"
              type={passwordVisible ? "text" : "password"}
              autoComplete="new-password"
              required
              minLength={12}
              maxLength={256}
              disabled={pending}
            />
          </div>
        </div>
        {error ? (
          <div
            className="auth-error-summary"
            role="alert"
            tabIndex={-1}
            ref={errorRef}
          >
            <strong>Password reset could not be completed</strong>
            <p>{error}</p>
          </div>
        ) : null}
        <button className="button button--ink button--full" disabled={pending}>
          {pending ? "Updating…" : "Update password"}
        </button>
      </form>
    </div>
  );
}
