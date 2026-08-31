"use client";

import { ArrowRight, Eye, EyeOff, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { googleAuthStartUrl } from "../lib/auth-links";
import { ApiError, createLearnerApi } from "../lib/learner-api";
import { ROUTES } from "../lib/routes";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The request did not finish. Check your connection and try again.";
}

type LoginFormProps = {
  sessionExpired?: boolean;
};

export function LoginForm({ sessionExpired = false }: LoginFormProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verificationRequired, setVerificationRequired] = useState(false);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const authenticateUrl = googleAuthStartUrl("authenticate");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setVerificationRequired(false);
    const values = new FormData(event.currentTarget);
    try {
      await createLearnerApi().loginPassword(
        String(values.get("email") ?? ""),
        String(values.get("password") ?? ""),
      );
      window.location.assign(ROUTES.learnerHome);
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
        Use your verified email and password to continue from your saved
        learning state.
      </p>
      {sessionExpired ? (
        <div className="auth-notice" role="status">
          <ShieldCheck size={18} aria-hidden="true" />
          <span>Your progress and saved workbook evidence are still safe.</span>
        </div>
      ) : null}
      <form className="stack-form" onSubmit={submit}>
        <div className="field-group">
          <label htmlFor="login-email">Email address</label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="email"
            inputMode="email"
            required
            disabled={pending}
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
              disabled={pending}
            />
            <button
              className="auth-password-toggle"
              type="button"
              aria-label={passwordVisible ? "Hide password" : "Show password"}
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
        {error ? (
          <div className="form-message form-message--error" role="alert">
            <p>{error}</p>
            {verificationRequired ? (
              <Link className="text-link" href={ROUTES.verifyEmail}>
                Request a fresh verification link
              </Link>
            ) : null}
          </div>
        ) : null}
        <button className="button button--ink button--full" disabled={pending}>
          {pending ? "Signing in…" : "Sign in"}
          <ArrowRight size={17} aria-hidden="true" />
        </button>
        <Link className="text-link" href={ROUTES.forgotPassword}>
          Forgot your password?
        </Link>
      </form>
      <div className="auth-divider" aria-hidden="true">
        <span>or</span>
      </div>
      <a className="button button--outline button--full" href={authenticateUrl}>
        Continue with Google
      </a>
      <div className="auth-card__footer">
        <span>New to Authority Closers?</span>
        <Link href={ROUTES.register}>Create a free account</Link>
      </div>
    </div>
  );
}
