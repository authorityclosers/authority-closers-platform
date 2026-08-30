"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { googleAuthStartUrl } from "../lib/auth-links";
import { ApiError, createLearnerApi } from "../lib/learner-api";
import { ROUTES } from "../lib/routes";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The request did not finish. Check your connection and try again.";
}

export function LoginForm() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verificationRequired, setVerificationRequired] = useState(false);
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
    <div className="auth-card">
      <div className="auth-card__topline">
        <span className="auth-card__icon">
          <ShieldCheck size={18} aria-hidden="true" />
        </span>
        <span>Secure session boundary</span>
      </div>
      <h2>Come back to the work.</h2>
      <p className="auth-card__intro">
        Use your verified email and password. The browser receives only an
        opaque, secure session cookie.
      </p>
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
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            disabled={pending}
          />
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
          {pending ? "Signing in…" : "Continue with email"}
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
