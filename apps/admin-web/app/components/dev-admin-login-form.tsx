"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

function safeError(payload: unknown): string {
  if (typeof payload !== "object" || payload === null) {
    return "The admin sign-in request was rejected.";
  }
  const detail = (payload as Record<string, unknown>).detail;
  return typeof detail === "string" && detail.trim()
    ? detail
    : "The admin sign-in request was rejected.";
}

export function DevAdminLoginForm() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const values = new FormData(event.currentTarget);
    try {
      const response = await fetch("/v1/auth/password/login", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          email: String(values.get("email") ?? ""),
          password: String(values.get("password") ?? ""),
        }),
      });
      if (!response.ok) {
        let payload: unknown = null;
        try {
          payload = await response.json();
        } catch {
          payload = null;
        }
        throw new Error(safeError(payload));
      }
      window.location.assign("/");
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The admin sign-in request did not finish.",
      );
      setPending(false);
    }
  }

  return (
    <form className="dev-admin-login-card" onSubmit={submit}>
      <div className="dev-admin-login-kicker">
        <ShieldCheck size={18} aria-hidden="true" />
        Verified staging admin session
      </div>
      <h1>Sign in to the local admin workspace.</h1>
      <p>
        Use the normal staging admin email and password. Cloudflare Access stays
        server-side; this browser receives only an ephemeral localhost cookie.
      </p>
      <label htmlFor="admin-login-email">Email address</label>
      <input
        id="admin-login-email"
        name="email"
        type="email"
        autoComplete="username"
        required
        disabled={pending}
      />
      <label htmlFor="admin-login-password">Password</label>
      <input
        id="admin-login-password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        disabled={pending}
      />
      {error ? (
        <div
          className="dev-admin-login-error"
          role="alert"
          tabIndex={-1}
          ref={errorRef}
        >
          {error}
        </div>
      ) : null}
      <button className="dev-admin-login-submit" disabled={pending}>
        {pending ? "Verifying…" : "Sign in"}
        <ArrowRight size={17} aria-hidden="true" />
      </button>
    </form>
  );
}
