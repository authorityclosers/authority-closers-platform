"use client";

import {
  ArrowRight,
  CircleAlert,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  ApiError,
  createLearnerApi,
  type LearnerConsentResponse,
} from "../lib/learner-api";
import { ROUTES } from "../lib/routes";

const api = createLearnerApi();

export function ConsentRenewalRuntime({
  returnHref,
  loginHref,
}: {
  returnHref: string;
  loginHref: string;
}) {
  const router = useRouter();
  const [consent, setConsent] = useState<LearnerConsentResponse | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void api
      .consent()
      .then((value) => {
        if (!active) return;
        setConsent(value);
        if (value.status === "current") setAccepted(true);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(
          reason instanceof ApiError && reason.status === 401
            ? "Sign in with your verified learner account to review the current consent."
            : "The current consent document could not be loaded. Please try again.",
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accepted) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.renewConsent();
      setConsent(updated);
      router.replace(returnHref);
    } catch (reason: unknown) {
      setError(
        reason instanceof ApiError && reason.status === 403
          ? "Only an active, email-verified learner account can renew consent."
          : "The consent update could not be saved. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="surface-state" role="status" aria-live="polite">
        <LoaderCircle className="spin" size={22} aria-hidden="true" />
        <h1>Loading the current consent</h1>
        <p>The server is selecting the published document for this account.</p>
      </div>
    );
  }

  if (error && !consent) {
    return (
      <section
        className="auth-card clarity-auth-card"
        aria-labelledby="consent-error-title"
      >
        <CircleAlert size={22} aria-hidden="true" />
        <h1 id="consent-error-title">Consent review needs your account</h1>
        <p>{error}</p>
        <Link className="button button--ink button--full" href={loginHref}>
          Sign in to continue <ArrowRight size={17} aria-hidden="true" />
        </Link>
      </section>
    );
  }

  if (!consent) return null;

  return (
    <section
      className="auth-card clarity-auth-card"
      aria-labelledby="consent-title"
    >
      <div className="callback-card__icon">
        <ShieldCheck size={22} aria-hidden="true" />
      </div>
      <p className="eyebrow">
        <span aria-hidden="true" /> Current learner consent
      </p>
      <h1 id="consent-title">Review the current Terms and Privacy notice</h1>
      <p>
        Your existing account and learning history stay in place. Access to a
        course may wait until this current published document is accepted.
      </p>
      <p className="boundary-card" role="note">
        Server document version: <strong>{consent.document.version}</strong>
      </p>
      <p>{consent.document.acknowledgement}</p>
      <p>
        Read the <Link href={consent.document.terms_path}>Terms</Link> and{" "}
        <Link href={consent.document.privacy_path}>Privacy notice</Link> before
        accepting.
      </p>
      <form onSubmit={submit}>
        <label className="consent-check">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(event) => setAccepted(event.target.checked)}
          />
          <span>{consent.document.acknowledgement}</span>
        </label>
        {error ? (
          <p role="alert" className="form-error">
            {error}
          </p>
        ) : null}
        <button
          className="button button--ink button--full"
          type="submit"
          disabled={!accepted || saving}
        >
          {saving ? "Saving consent…" : "Accept and return to course"}
          <ArrowRight size={17} aria-hidden="true" />
        </button>
      </form>
      <Link className="button button--outline button--full" href={ROUTES.home}>
        Return to public home
      </Link>
    </section>
  );
}
