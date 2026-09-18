"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import { BrandMark } from "@ac/ui";
import Link from "next/link";
import {
  type CSSProperties,
  type FormEvent,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

const GOOGLE_AUTH_START =
  "/v1/auth/google/start?action=authenticate&surface=sales_xray&return_path=%2F";
const LOGIN_ERROR =
  "We couldn’t sign you in. Check your email and password, then try again.";
const subscribeHostname = () => () => {};
const serverHostname = () => "";

const LEARNER_ORIGINS_BY_SOURCE_HOST = {
  "salesxray-staging.authorityclosers.com":
    "https://learner-staging.authorityclosers.com",
  "salesxray.authorityclosers.com": "https://learner.authorityclosers.com",
} as const;

export type LearnerAuthLinks = Readonly<{
  registerHref: string | null;
  forgotPasswordHref: string | null;
}>;

/**
 * Only the two source-owned hosts may construct an external learner link.
 * Unknown hosts stay guidance-only so a forwarded Host header or local origin
 * can never become an arbitrary redirect destination.
 */
export function learnerAuthLinksForHost(hostname: string): LearnerAuthLinks {
  const learnerOrigin =
    LEARNER_ORIGINS_BY_SOURCE_HOST[
      hostname.toLowerCase() as keyof typeof LEARNER_ORIGINS_BY_SOURCE_HOST
    ];
  if (!learnerOrigin) return { registerHref: null, forgotPasswordHref: null };
  return {
    registerHref: `${learnerOrigin}/register`,
    forgotPasswordHref: `${learnerOrigin}/forgot-password`,
  };
}

const shellStyle: CSSProperties = {
  minHeight: "100vh",
  display: "grid",
  placeItems: "center",
  padding: "32px 20px",
  background: "var(--canvas)",
};
const cardStyle: CSSProperties = {
  width: "min(100%, 440px)",
  padding: "34px",
  border: "1px solid var(--border)",
  borderRadius: 14,
  background: "var(--surface)",
  boxShadow: "var(--shadow)",
};
const fieldStyle: CSSProperties = {
  display: "grid",
  gap: 7,
};
const inputStyle: CSSProperties = {
  width: "100%",
  minHeight: 46,
  padding: "10px 12px",
  border: "1px solid var(--border)",
  borderRadius: 6,
  background: "var(--surface)",
  color: "var(--text)",
};
const linkStyle: CSSProperties = {
  color: "var(--action)",
  fontSize: 12,
  fontWeight: 650,
};

export function LoginForm() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const hostname = useSyncExternalStore(
    subscribeHostname,
    () => window.location.hostname,
    serverHostname,
  );
  const links = learnerAuthLinksForHost(hostname);
  const errorRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setError("");
    const form = event.currentTarget;
    const values = new FormData(form);
    const email = String(values.get("email") ?? "").trim();
    const password = String(values.get("password") ?? "");
    try {
      const response = await fetch("/v1/auth/password/login", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          "content-type": "application/json",
          accept: "application/json",
        },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) throw new Error("login_rejected");
      if (mounted.current) {
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- A successful login needs a fresh same-origin document and session.
        window.location.assign("/");
      }
    } catch {
      if (mounted.current) setError(LOGIN_ERROR);
    } finally {
      const passwordInput = form.elements.namedItem("password");
      if (passwordInput instanceof HTMLInputElement) passwordInput.value = "";
      if (mounted.current) setPending(false);
      inFlight.current = false;
    }
  }

  const actionButtonStyle: CSSProperties = {
    width: "100%",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 9,
  };

  return (
    <main className="xray-app simple-app" data-theme="light" style={shellStyle}>
      <section style={cardStyle} aria-labelledby="sales-xray-login-heading">
        <header style={{ display: "grid", gap: 15, marginBottom: 28 }}>
          <Link
            href="/"
            aria-label="Sales Xray home"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 12,
              width: "fit-content",
              color: "var(--text)",
              textDecoration: "none",
              fontSize: 16,
              fontWeight: 650,
            }}
          >
            <BrandMark
              width={30}
              height={30}
              aria-hidden="true"
              style={{ color: "var(--mint)" }}
            />
            <span>
              Dipak’s Sales Xray
              <small
                style={{
                  display: "block",
                  marginTop: 2,
                  color: "var(--muted)",
                  fontSize: 9,
                  letterSpacing: 1.7,
                }}
              >
                AUTHORITY CLOSERS
              </small>
            </span>
          </Link>
          <p
            style={{
              margin: 0,
              color: "var(--muted)",
              fontSize: 11,
              fontWeight: 650,
              letterSpacing: 1.6,
              textTransform: "uppercase",
            }}
          >
            Existing account access
          </p>
        </header>

        <h1
          id="sales-xray-login-heading"
          style={{ margin: "0 0 9px", fontSize: 32, letterSpacing: -0.8 }}
        >
          Welcome back.
        </h1>
        <p style={{ margin: "0 0 26px", color: "var(--muted)" }}>
          Sign in with your existing Authority Closers account to open your
          calls and reports.
        </p>

        <div
          style={{
            display: "flex",
            gap: 10,
            alignItems: "flex-start",
            marginBottom: 22,
            padding: "12px 13px",
            border: "1px solid var(--border)",
            borderRadius: 8,
            background: "var(--mint-bg)",
            color: "var(--mint)",
            fontSize: 12,
          }}
        >
          <ShieldCheck size={17} aria-hidden="true" />
          <span>Your AC account keeps your calls private.</span>
        </div>

        <form
          method="post"
          onSubmit={submit}
          aria-busy={pending}
          style={{ display: "grid", gap: 17 }}
        >
          <div style={fieldStyle}>
            <label htmlFor="sales-xray-email">Email address</label>
            <input
              id="sales-xray-email"
              name="email"
              type="email"
              autoComplete="username"
              inputMode="email"
              required
              disabled={pending}
              style={inputStyle}
            />
          </div>
          <div style={fieldStyle}>
            <label htmlFor="sales-xray-password">Password</label>
            <input
              id="sales-xray-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              disabled={pending}
              style={inputStyle}
            />
          </div>

          {error ? (
            <div
              ref={errorRef}
              role="alert"
              tabIndex={-1}
              style={{
                padding: "11px 13px",
                border: "1px solid var(--danger)",
                borderRadius: 7,
                background: "var(--danger-bg)",
                color: "var(--danger)",
                fontSize: 12,
              }}
            >
              {error}
            </div>
          ) : null}

          <button
            type="submit"
            className="primary-button"
            disabled={pending}
            style={actionButtonStyle}
          >
            {pending ? "Signing in…" : "Sign in"}
            <ArrowRight size={17} aria-hidden="true" />
          </button>
        </form>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            margin: "23px 0",
            color: "var(--muted)",
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: 1.5,
          }}
        >
          <span style={{ height: 1, flex: 1, background: "var(--border)" }} />
          <span>or</span>
          <span style={{ height: 1, flex: 1, background: "var(--border)" }} />
        </div>

        <a
          className="secondary-button"
          href={GOOGLE_AUTH_START}
          style={actionButtonStyle}
        >
          Continue with Google
        </a>

        <div
          style={{
            display: "grid",
            gap: 10,
            marginTop: 25,
            paddingTop: 20,
            borderTop: "1px solid var(--border)",
            fontSize: 12,
          }}
        >
          {links.forgotPasswordHref ? (
            <a href={links.forgotPasswordHref} style={linkStyle}>
              Forgot your password?
            </a>
          ) : (
            <p style={{ margin: 0, color: "var(--muted)" }}>
              Reset your password in the Authority Closers learning app.
            </p>
          )}
          {links.registerHref ? (
            <a href={links.registerHref} style={linkStyle}>
              Create a learner account
            </a>
          ) : (
            <p style={{ margin: 0, color: "var(--muted)" }}>
              Create your account in the Authority Closers learning app.
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
