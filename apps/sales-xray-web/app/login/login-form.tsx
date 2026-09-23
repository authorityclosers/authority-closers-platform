"use client";

import { ArrowRight, AudioLines, ShieldCheck } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import styles from "./login-form.module.css";

const GOOGLE_AUTH_START =
  "/v1/auth/google/start?action=authenticate&surface=sales_xray&return_path=%2F";
const LOGIN_ERROR =
  "We couldn’t sign you in. Check your email and password, then try again.";
const WAVE_HEIGHTS = [
  17, 25, 19, 37, 52, 34, 59, 73, 46, 28, 64, 82, 56, 36, 67, 88, 62, 40, 74,
  54, 82, 59, 35, 64, 45, 71, 39, 25, 49, 28, 17,
] as const;
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

  return (
    <main className={`xray-app ${styles.shell}`} data-theme="light">
      <div className={styles.layout}>
        <section className={styles.story} aria-label="About Sales Xray">
          <Link href="/" className={styles.brand} aria-label="Sales Xray home">
            <Image
              src="/brand/ac-v0.1/symbol.svg"
              alt=""
              width={48}
              height={48}
              priority
            />
            <Image
              src="/brand/ac-v0.1/sales-xray-wordmark.svg"
              alt="Sales Xray by Authority Closers"
              width={147}
              height={52}
              priority
            />
          </Link>
          <div className={styles.storyBody}>
            <p className={styles.storyKicker}>TURN CALLS INTO CLARITY</p>
            <h2>
              Better conversations
              <br />
              begin with <em>insight.</em>
            </h2>
            <p className={styles.storyLead}>
              Return to your calls and reports, and keep coaching with clarity.
            </p>
            <div className={styles.visual} aria-hidden="true">
              <div className={styles.visualRing} />
              <div className={styles.wave}>
                {WAVE_HEIGHTS.map((height, index) => (
                  <span
                    key={index}
                    style={{
                      height: `${height}%`,
                      animationDelay: `${-index * 64}ms`,
                    }}
                  />
                ))}
              </div>
              <div className={styles.signalTag}>
                <AudioLines size={17} /> CONVERSATION STUDIO
              </div>
            </div>
          </div>
          <div className={styles.storyFooter}>
            <ShieldCheck size={17} aria-hidden="true" /> One Authority Closers
            account for your calls and reports.
          </div>
        </section>

        <section
          className={styles.formSide}
          aria-labelledby="sales-xray-login-heading"
        >
          <div className={styles.formPanel}>
            <div className={styles.formHeading}>
              <p className={styles.eyebrow}>EXISTING ACCOUNT ACCESS</p>
              <h1 id="sales-xray-login-heading">
                Welcome back<span>.</span>
              </h1>
              <p>
                Sign in with your Authority Closers account to open your saved
                calls and reports.
              </p>
            </div>

            <form
              method="post"
              onSubmit={submit}
              aria-busy={pending}
              className={styles.form}
            >
              <div className={styles.field}>
                <label htmlFor="sales-xray-email">Email address</label>
                <input
                  id="sales-xray-email"
                  name="email"
                  type="email"
                  autoComplete="username"
                  inputMode="email"
                  placeholder="you@company.com"
                  required
                  disabled={pending}
                />
              </div>
              <div className={styles.field}>
                <label htmlFor="sales-xray-password">Password</label>
                <input
                  id="sales-xray-password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  required
                  disabled={pending}
                />
              </div>
              {error ? (
                <div
                  ref={errorRef}
                  role="alert"
                  tabIndex={-1}
                  className={styles.error}
                >
                  {error}
                </div>
              ) : null}
              <button
                type="submit"
                className={styles.submit}
                disabled={pending}
              >
                {pending ? "Signing in…" : "Sign in to Sales Xray"}
                <ArrowRight size={18} aria-hidden="true" />
              </button>
            </form>

            <div className={styles.divider}>
              <span>or continue with</span>
            </div>
            <a className={styles.google} href={GOOGLE_AUTH_START}>
              <span className={styles.googleMark} aria-hidden="true">
                G
              </span>
              Google
            </a>

            <div className={styles.helpLinks}>
              {links.forgotPasswordHref ? (
                <a href={links.forgotPasswordHref}>Forgot your password?</a>
              ) : (
                <p>
                  Reset your password in the Authority Closers learning app.
                </p>
              )}
              {links.registerHref ? (
                <a href={links.registerHref}>
                  Create a learner account{" "}
                  <ArrowRight size={15} aria-hidden="true" />
                </a>
              ) : (
                <p>
                  Create your account in the Authority Closers learning app.
                </p>
              )}
            </div>
          </div>
          <p className={styles.formFooter}>
            <ShieldCheck size={15} aria-hidden="true" /> Your AC account keeps
            your calls private.
          </p>
        </section>
      </div>
    </main>
  );
}
