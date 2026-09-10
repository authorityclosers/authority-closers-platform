"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { loginLocalAdmin } from "../lib/local-admin-login";

const subscribeHydration = () => () => {};

function safeError(payload: unknown): string {
  if (typeof payload !== "object" || payload === null) {
    return "The admin sign-in request was rejected.";
  }
  const detail = (payload as Record<string, unknown>).detail;
  return typeof detail === "string" && detail.trim()
    ? detail
    : "The admin sign-in request was rejected.";
}

export function DevAdminLoginForm({
  mode = "staging-authenticated",
}: {
  mode?: "local-sandbox" | "staging-authenticated";
}) {
  const [pending, setPending] = useState(false);
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    () => true,
    () => false,
  );
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
      if (mode === "local-sandbox") {
        await loginLocalAdmin(
          String(values.get("email") ?? ""),
          String(values.get("password") ?? ""),
          String(values.get("tenant_id") ?? ""),
        );
        window.location.assign("/");
        return;
      }
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
    <form className="dev-admin-login-card" method="post" onSubmit={submit}>
      <div className="dev-admin-login-kicker">
        <ShieldCheck size={18} aria-hidden="true" />
        {mode === "local-sandbox"
          ? "Local sandbox session"
          : "Verified staging admin session"}
      </div>
      <h1>Sign in to the local admin workspace.</h1>
      <p>
        {mode === "local-sandbox"
          ? "Use a local test account and its tenant ID. Your real local session determines which Studio or admin actions are available. No staging account or remote data is used."
          : "Use the normal staging admin email and password. Cloudflare Access stays server-side; this browser receives only an ephemeral localhost cookie."}
      </p>
      <label htmlFor="admin-login-email">Email address</label>
      <input
        id="admin-login-email"
        name="email"
        type="email"
        autoComplete="username"
        required
        disabled={pending || !hydrated}
      />
      <label htmlFor="admin-login-password">Password</label>
      <input
        id="admin-login-password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        disabled={pending || !hydrated}
      />
      {mode === "local-sandbox" ? (
        <>
          <label htmlFor="admin-login-tenant">Local tenant ID</label>
          <input
            id="admin-login-tenant"
            name="tenant_id"
            type="text"
            autoComplete="off"
            required
            disabled={pending || !hydrated}
            aria-describedby="admin-login-tenant-help"
          />
          <p id="admin-login-tenant-help">
            Use the tenant ID from your local sandbox account setup.
          </p>
        </>
      ) : null}
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
      <button
        className="dev-admin-login-submit"
        disabled={pending || !hydrated}
      >
        {pending ? "Verifying…" : "Sign in"}
        <ArrowRight size={17} aria-hidden="true" />
      </button>
    </form>
  );
}
