"use client";

import {
  ArrowLeft,
  ArrowRight,
  AudioLines,
  Check,
  Eye,
  EyeOff,
  FileAudio,
  FileText,
  LoaderCircle,
  Mail,
  ShieldCheck,
  Sparkles,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
} from "react";
import { BrandMark } from "./shell/brand-lockup";
import { ThemeToggle } from "./shell/theme-toggle";
import {
  emailCodeRequest,
  isAuthCompleteMessage,
  maskedEmail,
  parseAuthenticatedAccount,
  parseCodeTiming,
  parseEmailCodeConfig,
  parseAuthCompletionUrl,
  passwordLogin,
  readCanonicalSession,
  readGoogleCompletion,
  type AuthCompletionResult,
  type EmailCodeConfig,
} from "./account-auth-client";
import styles from "./account-auth.module.css";

export type AccountAuthPreviewState = "auth.email" | "auth.code" | "auth.error";

const PREVIEW_CONFIG: EmailCodeConfig = {
  enabled: true,
  consent_version: "review-only",
  google_enabled: true,
  expires_in_seconds: 600,
  resend_after_seconds: 60,
};
const XRAY_FEATURES = [
  { Icon: UsersRound, label: "Know who said what" },
  { Icon: Sparkles, label: "Find the moments that matter" },
  { Icon: FileText, label: "Leave with a clear next step" },
] as const;

// Google sign-in cannot finish on the dev site until dev has its own sign-in
// server (AUT-157): Google returns to staging, which cannot see the dev start.
const DEV_HOST = "salesxray-dev.authorityclosers.com";
const noHostSubscription = () => () => {};
const readGoogleBlocked = () => window.location.hostname === DEV_HOST;

function GoogleMark() {
  // Google's own four-colour "G", as its sign-in branding requires.
  return (
    <svg
      className={styles.googleMark}
      viewBox="0 0 48 48"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"
      />
    </svg>
  );
}
const subscribeHostname = () => () => {};
const serverHostname = () => "";
const LEARNER_ORIGINS_BY_SOURCE_HOST = {
  "salesxray-staging.authorityclosers.com":
    "https://learner-staging.authorityclosers.com",
  "salesxray.authorityclosers.com": "https://learner.authorityclosers.com",
} as const;

/** Only source-owned hosts may provide a learner recovery destination. */
export function learnerAuthLinksForHost(hostname: string) {
  const origin =
    LEARNER_ORIGINS_BY_SOURCE_HOST[
      hostname.toLowerCase() as keyof typeof LEARNER_ORIGINS_BY_SOURCE_HOST
    ];
  return origin
    ? {
        registerHref: `${origin}/register`,
        forgotPasswordHref: `${origin}/forgot-password`,
      }
    : { registerHref: null, forgotPasswordHref: null };
}

export function AccountAuth({
  selectedFile,
  onAuthenticated,
  onCancel,
  previewState,
}: {
  selectedFile?: { name: string; size: number } | null;
  onAuthenticated: () => void;
  onCancel?: (selectedFile: { name: string; size: number }) => void;
  previewState?: AccountAuthPreviewState;
}) {
  const preview = process.env.NODE_ENV !== "production" && !!previewState;
  const [config, setConfig] = useState<EmailCodeConfig | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [email, setEmail] = useState(
    previewState === "auth.code" ? "sample@example.test" : "",
  );
  const [consent, setConsent] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [step, setStep] = useState<"email" | "code" | "password" | "confirmed">(
    previewState === "auth.code" ? "code" : "email",
  );
  const [pending, setPending] = useState(false);
  const [popupActive, setPopupActive] = useState(false);
  const [sessionCheckNeeded, setSessionCheckNeeded] = useState(false);
  const [error, setError] = useState("");
  const [configError, setConfigError] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [expiresAt, setExpiresAt] = useState(0);
  const [now, setNow] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const popup = useRef<Window | null>(null);
  const popupFlow = useRef<string | null>(null);
  const popupPoll = useRef<ReturnType<typeof setInterval> | null>(null);
  const popupMessage = useRef<((event: MessageEvent) => void) | null>(null);
  const popupOutcome = useRef<AuthCompletionResult | null>(null);
  const confirmingPopup = useRef(false);
  const errorRef = useRef<HTMLParagraphElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const verified = useRef(false);
  const hostname = useSyncExternalStore(
    subscribeHostname,
    () => window.location.hostname,
    serverHostname,
  );
  // The server snapshot is empty until React can handle this page's clicks.
  const interactive = hostname !== "";
  const learnerLinks = learnerAuthLinksForHost(hostname);
  const activeConfig = preview ? PREVIEW_CONFIG : config;
  const displayedStep = preview
    ? previewState === "auth.code"
      ? "code"
      : "email"
    : step;
  const displayedEmail =
    previewState === "auth.code" && preview ? "sample@example.test" : email;

  useEffect(() => {
    if (preview) return;
    const request = new AbortController();
    emailCodeRequest("config", request.signal)
      .then(parseEmailCodeConfig)
      .then((value) => {
        if (!request.signal.aborted) {
          setConfig(value);
          setConfigError(false);
        }
      })
      .catch(() => {
        if (!request.signal.aborted) setConfigError(true);
      });
    return () => request.abort();
  }, [loadAttempt, preview]);
  useEffect(
    () => () => {
      controller.current?.abort();
      if (popupPoll.current) clearInterval(popupPoll.current);
      if (popupMessage.current)
        window.removeEventListener("message", popupMessage.current);
      popup.current?.close();
    },
    [],
  );
  useEffect(() => {
    if (step !== "code") return;
    codeRef.current?.focus();
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [step]);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  function complete() {
    if (preview || verified.current) return;
    verified.current = true;
    setStep("confirmed");
    onAuthenticated();
  }

  async function sendCode(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (
      preview ||
      !activeConfig?.enabled ||
      !activeConfig.consent_version ||
      !consent ||
      inFlight.current ||
      Date.now() < retryAt
    )
      return;
    const address = email.trim();
    if (!address || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) return;
    inFlight.current = true;
    const request = new AbortController();
    controller.current = request;
    setPending(true);
    setError("");
    try {
      const current = parseEmailCodeConfig(
        await emailCodeRequest("config", request.signal),
      );
      if (request.signal.aborted) return;
      setConfig(current);
      if (
        !current.enabled ||
        current.consent_version !== activeConfig.consent_version
      ) {
        setConsent(false);
        setStep("email");
        setConfigError(false);
        setError(
          "The Terms or sign-in settings changed. Review them and request a new code.",
        );
        return;
      }
      const body = await emailCodeRequest("request", request.signal, {
        email: address,
        consent: true,
        age_attested: true,
        consent_version: activeConfig.consent_version,
        surface: "sales_xray",
        return_path: "/",
      });
      const timing = parseCodeTiming(body);
      if (
        !body ||
        typeof body !== "object" ||
        !("accepted" in body) ||
        body.accepted !== true
      )
        throw new Error("not-accepted");
      if (request.signal.aborted) return;
      const time = Date.now();
      setEmail(address);
      setNow(time);
      setRetryAt(time + timing.resend_after_seconds * 1000);
      setExpiresAt(time + timing.expires_in_seconds * 1000);
      setSessionCheckNeeded(false);
      setStep("code");
      if (codeRef.current) codeRef.current.value = "";
    } catch (failure) {
      if (
        !request.signal.aborted &&
        !(await refreshConsentAfterFailure(request.signal))
      )
        setError(
          failure instanceof Error && failure.message === "rate-limited"
            ? "Please wait a moment before requesting another code."
            : "We couldn’t send a code just now. Please try again.",
        );
    } finally {
      inFlight.current = false;
      if (!request.signal.aborted) setPending(false);
    }
  }

  async function refreshConsentAfterFailure(signal: AbortSignal) {
    try {
      const current = parseEmailCodeConfig(
        await emailCodeRequest("config", signal),
      );
      if (signal.aborted) return false;
      setConfig(current);
      if (
        !current.enabled ||
        current.consent_version !== activeConfig?.consent_version
      ) {
        setConsent(false);
        setStep("email");
        setConfigError(false);
        setError(
          "The Terms or sign-in settings changed. Review them and request a new code.",
        );
        return true;
      }
    } catch {
      // A failed refresh gives no account-existence signal. Keep the safe
      // retry path on the code screen with the user's selected file intact.
    }
    return false;
  }

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = codeRef.current?.value.replace(/\s/g, "") ?? "";
    if (preview || inFlight.current || !/^\d{6}$/.test(code)) return;
    inFlight.current = true;
    const request = new AbortController();
    controller.current = request;
    setPending(true);
    setError("");
    let codeAccepted = false;
    try {
      parseAuthenticatedAccount(
        await emailCodeRequest("verify", request.signal, {
          email,
          code,
          surface: "sales_xray",
          return_path: "/",
        }),
      );
      codeAccepted = true;
      await readCanonicalSession(request.signal);
      if (!request.signal.aborted) complete();
    } catch {
      if (!request.signal.aborted) {
        if (codeAccepted) {
          setSessionCheckNeeded(true);
          setError(
            "Your code was accepted, but your account session could not be confirmed. Check again below.",
          );
        } else if (!(await refreshConsentAfterFailure(request.signal))) {
          setError(
            "That code could not be verified. Check the latest email, or request a new code.",
          );
        }
      }
    } finally {
      if (codeRef.current) codeRef.current.value = "";
      inFlight.current = false;
      if (!request.signal.aborted) setPending(false);
    }
  }

  async function checkVerifiedSession() {
    if (preview || inFlight.current || !sessionCheckNeeded) return;
    inFlight.current = true;
    const request = new AbortController();
    controller.current = request;
    setPending(true);
    setError("");
    try {
      await readCanonicalSession(request.signal);
      if (!request.signal.aborted) complete();
    } catch {
      if (!request.signal.aborted)
        setError(
          "Your account session still could not be confirmed. Try again or request a new code.",
        );
    } finally {
      inFlight.current = false;
      if (!request.signal.aborted) setPending(false);
    }
  }

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (preview || inFlight.current) return;
    const address = email.trim();
    const password = passwordRef.current?.value ?? "";
    if (!address || !password) return;
    inFlight.current = true;
    const request = new AbortController();
    controller.current = request;
    setPending(true);
    setError("");
    try {
      await passwordLogin(address, password, request.signal);
      if (!request.signal.aborted) complete();
    } catch {
      if (!request.signal.aborted)
        setError(
          "We couldn’t complete password sign-in. Check your details or try again later.",
        );
    } finally {
      if (passwordRef.current) passwordRef.current.value = "";
      setShowPassword(false);
      inFlight.current = false;
      if (!request.signal.aborted) setPending(false);
    }
  }

  function clearPopup() {
    if (popupPoll.current) clearInterval(popupPoll.current);
    popupPoll.current = null;
    if (popupMessage.current)
      window.removeEventListener("message", popupMessage.current);
    popupMessage.current = null;
    popup.current?.close();
    popup.current = null;
    popupFlow.current = null;
    popupOutcome.current = null;
    setPopupActive(false);
  }

  function cancelGoogle() {
    controller.current?.abort();
    clearPopup();
    confirmingPopup.current = false;
    inFlight.current = false;
    setPending(false);
    setError("");
  }

  async function confirmGoogle() {
    if (
      preview ||
      !popup.current ||
      !popupFlow.current ||
      popupOutcome.current !== "success" ||
      confirmingPopup.current
    )
      return;
    confirmingPopup.current = true;
    const request = new AbortController();
    controller.current = request;
    try {
      await readGoogleCompletion(popupFlow.current, request.signal);
      if (request.signal.aborted) return;
      await readCanonicalSession(request.signal);
      if (!request.signal.aborted) {
        clearPopup();
        complete();
        inFlight.current = false;
        setPending(false);
      }
    } catch {
      if (!request.signal.aborted) {
        clearPopup();
        inFlight.current = false;
        setPending(false);
        setError(
          "Google sign-in could not be confirmed. Try again or use an email code.",
        );
      }
    } finally {
      confirmingPopup.current = false;
    }
  }

  function receiveGoogleResult(result: AuthCompletionResult) {
    if (!popup.current || !popupFlow.current || popupOutcome.current) return;
    popupOutcome.current = result;
    if (result === "success") {
      void confirmGoogle();
      return;
    }
    controller.current?.abort();
    clearPopup();
    inFlight.current = false;
    setPending(false);
    if (result === "review_terms") {
      setConsent(false);
      setLoadAttempt((attempt) => attempt + 1);
      setError(
        "Review the current Terms and Privacy notice, then try signing in again.",
      );
    } else if (result === "unavailable") {
      setError(
        "Google sign-in is unavailable right now. Try again or use an email code.",
      );
    } else {
      setError(
        "Google sign-in could not be completed. Try again or use an email code.",
      );
    }
  }

  function checkGoogleWindow() {
    const child = popup.current;
    const flow = popupFlow.current;
    if (!child || !flow) return;
    try {
      const url = child.location.href;
      const result = parseAuthCompletionUrl(url, window.location.origin, flow);
      if (result) {
        receiveGoogleResult(result);
        return;
      }
      const location = new URL(url);
      if (
        location.origin === window.location.origin &&
        location.pathname === "/auth/complete"
      ) {
        clearPopup();
        inFlight.current = false;
        setPending(false);
        setError(
          "Google sign-in could not be confirmed. Try again or use an email code.",
        );
        return;
      }
    } catch {
      // The provider page remains cross-origin until it returns here.
    }
    setError("Finish sign-in in the Google window, then check again.");
  }

  function google() {
    if (
      preview ||
      !activeConfig?.google_enabled ||
      !activeConfig.consent_version ||
      configError ||
      !consent ||
      inFlight.current
    )
      return;
    // Open a blank same-origin popup synchronously. Fresh policy is checked
    // before navigating it to Google, while the File stays in this document.
    const flow = crypto.randomUUID();
    const child = window.open(
      "about:blank",
      "sales-xray-sign-in",
      "popup,width=520,height=720",
    );
    if (!child) {
      setError(
        "Allow the sign-in window, or use an email code. This page stays open.",
      );
      return;
    }
    popup.current = child;
    popupFlow.current = flow;
    popupOutcome.current = null;
    setPopupActive(true);
    inFlight.current = true;
    setPending(true);
    setError("");
    const handleMessage = (event: MessageEvent) => {
      if (
        event.origin !== window.location.origin ||
        event.source !== popup.current ||
        !popupFlow.current ||
        !isAuthCompleteMessage(event.data, popupFlow.current)
      )
        return;
      receiveGoogleResult(event.data.auth_result);
    };
    popupMessage.current = handleMessage;
    window.addEventListener("message", handleMessage);
    popupPoll.current = setInterval(() => {
      cancelGoogle();
      setError("Google sign-in timed out. Try again or use an email code.");
    }, 5 * 60_000);
    const request = new AbortController();
    controller.current = request;
    void emailCodeRequest("config", request.signal)
      .then(parseEmailCodeConfig)
      .then((current) => {
        if (request.signal.aborted) return;
        setConfig(current);
        if (
          !current.google_enabled ||
          !current.consent_version ||
          current.consent_version !== activeConfig.consent_version
        ) {
          setConsent(false);
          setConfigError(false);
          clearPopup();
          inFlight.current = false;
          setPending(false);
          setError(
            "The Terms or sign-in settings changed. Review them before continuing.",
          );
          return;
        }
        const parameters = new URLSearchParams({
          action: "authenticate",
          surface: "sales_xray",
          consent: "true",
          age_attested: "true",
          consent_version: current.consent_version,
          return_path: `/auth/complete?flow=${flow}`,
        });
        child.location.assign(`/v1/auth/google/start?${parameters}`);
      })
      .catch(() => {
        if (request.signal.aborted) return;
        clearPopup();
        inFlight.current = false;
        setPending(false);
        setError("Sign-in settings could not be checked. Please try again.");
      });
  }

  const seconds = Math.max(0, Math.ceil((retryAt - now) / 1000));
  const expired = !preview && displayedStep === "code" && now >= expiresAt;
  const unavailable =
    configError ||
    (activeConfig != null && !activeConfig.enabled) ||
    (preview && previewState === "auth.error");
  const available =
    activeConfig?.enabled && !!activeConfig.consent_version && !unavailable;
  const googleBlocked = useSyncExternalStore(
    noHostSubscription,
    readGoogleBlocked,
    () => false,
  );
  const googleAvailable =
    !googleBlocked &&
    !!activeConfig?.google_enabled &&
    !!activeConfig.consent_version &&
    !configError &&
    !(preview && previewState === "auth.error");
  const brandContent = <BrandMark />;
  const heading =
    displayedStep === "code"
      ? "Check your email."
      : displayedStep === "confirmed"
        ? "Let’s get you ready."
        : displayedStep === "password"
          ? "Welcome back."
          : "Sign in or create your account";
  const lead =
    displayedStep === "code" ? (
      <>
        If this address can receive a sign-in code, check the inbox for{" "}
        <strong>{maskedEmail(displayedEmail)}</strong>. Owner and admin accounts
        never get codes: use Google or your password.
      </>
    ) : displayedStep === "confirmed" ? (
      "Opening your account securely…"
    ) : displayedStep === "password" ? (
      "Sign in with your existing Authority Closers password."
    ) : unavailable && !googleAvailable ? (
      "Sign in with your existing Authority Closers account."
    ) : (
      "Get a sign-in code by email, or use your existing password."
    );
  return (
    <section
      className={`xray-app ${styles.auth}`}
      aria-labelledby="account-auth-heading"
      aria-busy={pending}
      data-review-preview={preview ? "true" : undefined}
    >
      <header className={styles.header}>
        {selectedFile ? (
          onCancel ? (
            <button
              type="button"
              className={styles.brand}
              aria-label="Back to your call"
              onClick={() => onCancel(selectedFile)}
            >
              {brandContent}
            </button>
          ) : (
            <div className={styles.brand} aria-label="Sales Xray">
              {brandContent}
            </div>
          )
        ) : (
          <Link className={styles.brand} href="/" aria-label="Sales Xray home">
            {brandContent}
          </Link>
        )}
        <div className={styles.formBar}>
          {selectedFile && onCancel ? (
            <button
              type="button"
              className={styles.returnLink}
              onClick={() => onCancel(selectedFile)}
            >
              <ArrowLeft size={16} aria-hidden="true" /> Back to your call
            </button>
          ) : !selectedFile ? (
            <Link className={styles.returnLink} href="/">
              <ArrowLeft size={16} aria-hidden="true" /> Back to home
            </Link>
          ) : (
            <span />
          )}
          <ThemeToggle />
        </div>
      </header>
      <div className={styles.body}>
        <aside className={styles.stage}>
          <div className={styles.storyCopy}>
            <h2>
              Hear the <span className={styles.accent}>opportunity</span>
              <br />
              in every call.
            </h2>
            <p>Bring your conversation. Leave with a clearer next step.</p>
          </div>
          <ul className={styles.features}>
            {XRAY_FEATURES.map(({ Icon, label }) => (
              <li key={label}>
                <Icon size={16} aria-hidden="true" />
                {label}
              </li>
            ))}
          </ul>
          <p className={styles.shared}>
            <ShieldCheck size={15} aria-hidden="true" />
            One AC account. Your learning, calls and reports.
          </p>
        </aside>
        <div className={styles.formColumn}>
          <div className={styles.card}>
            <p className={styles.eyebrow}>
              {displayedStep === "code"
                ? "One quick check"
                : displayedStep === "confirmed"
                  ? "You’re signed in"
                  : displayedStep === "password"
                    ? "Existing AC account"
                    : "Welcome to Sales Xray"}
            </p>
            <h1 id="account-auth-heading">{heading}</h1>
            <p className={styles.lead}>{lead}</p>
            <p
              ref={errorRef}
              tabIndex={-1}
              role={error ? "alert" : undefined}
              className={styles.error}
            >
              {error}
            </p>

            {displayedStep === "confirmed" ? (
              <div className={styles.confirmed}>
                <span className={styles.confirmedMark}>
                  <Check aria-hidden="true" />
                </span>
                Account confirmed
              </div>
            ) : (
              <>
                {displayedStep !== "password" && unavailable ? (
                  <div role="status" className={styles.notice}>
                    <span>Email code sign-in isn’t available right now.</span>
                    <div className={styles.noticeActions}>
                      <button
                        type="button"
                        className={styles.noticePrimary}
                        disabled={preview || !interactive}
                        onClick={() => {
                          setStep("password");
                          setError("");
                        }}
                      >
                        Use my existing password{" "}
                        <ArrowRight size={16} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className={styles.textButton}
                        disabled={preview}
                        onClick={() => setLoadAttempt((value) => value + 1)}
                      >
                        Check code sign-in again
                      </button>
                    </div>
                  </div>
                ) : displayedStep !== "password" && !activeConfig ? (
                  <p role="status" className={styles.notice}>
                    <LoaderCircle className={styles.spin} size={18} />
                    Preparing secure sign-in…
                  </p>
                ) : null}
                {displayedStep === "email" &&
                unavailable &&
                !googleAvailable ? null : displayedStep === "email" ? (
                  <>
                    {available && (
                      <div className={styles.emailField}>
                        {" "}
                        <label htmlFor="account-email">Email address</label>
                        <div className={styles.inputWrap}>
                          <Mail size={18} aria-hidden="true" />
                          <input
                            id="account-email"
                            form="account-email-form"
                            autoCapitalize="none"
                            spellCheck={false}
                            name="email"
                            type="email"
                            autoComplete="email"
                            maxLength={320}
                            value={email}
                            onChange={(event) => setEmail(event.target.value)}
                            placeholder="you@company.com"
                            required
                            disabled={preview || pending}
                          />
                        </div>
                      </div>
                    )}
                    <label
                      className={styles.consent}
                      data-checked={consent ? "true" : undefined}
                    >
                      <input
                        type="checkbox"
                        form="account-email-form"
                        checked={consent}
                        onChange={(event) => setConsent(event.target.checked)}
                        disabled={preview || pending}
                        required
                      />
                      <span className={styles.check} aria-hidden="true">
                        <svg viewBox="0 0 16 16">
                          <path d="M3.5 8.4 6.6 11.3 12.5 5" />
                        </svg>
                      </span>
                      <span>
                        I confirm that I am 18 or older and accept the current
                        Authority Closers{" "}
                        <a
                          href="https://app.authorityclosers.com/terms"
                          target="_blank"
                          rel="noreferrer"
                        >
                          Terms
                        </a>{" "}
                        and{" "}
                        <a
                          href="https://app.authorityclosers.com/privacy"
                          target="_blank"
                          rel="noreferrer"
                        >
                          Privacy notice
                        </a>{" "}
                        for my learner account.
                      </span>
                    </label>
                    {googleAvailable && (
                      <button
                        type="button"
                        className={styles.google}
                        onClick={google}
                        disabled={preview || !consent || pending}
                        aria-describedby={
                          !consent ? "account-google-consent-hint" : undefined
                        }
                      >
                        <GoogleMark />
                        Continue with Google
                      </button>
                    )}
                    {googleAvailable && !consent && (
                      <p
                        id="account-google-consent-hint"
                        className={styles.consentHint}
                      >
                        Tick the box above to continue with Google or email.
                      </p>
                    )}
                    {googleAvailable && available && (
                      <div className={styles.divider}>
                        <span>or use email</span>
                      </div>
                    )}
                    <form
                      id="account-email-form"
                      onSubmit={sendCode}
                      className={styles.form}
                    >
                      {available && (
                        <>
                          <button
                            type="submit"
                            className={styles.primary}
                            disabled={
                              preview || !available || !consent || pending
                            }
                          >
                            {pending ? (
                              <>
                                <LoaderCircle
                                  className={styles.spin}
                                  size={18}
                                />
                                Sending…
                              </>
                            ) : (
                              <>
                                Send sign-in code
                                <ArrowRight
                                  size={18}
                                  className={styles.arrow}
                                />
                              </>
                            )}
                          </button>
                        </>
                      )}
                    </form>
                    {popupActive && pending && (
                      <div className={styles.popupActions} role="status">
                        <p>Finish sign-in in the Google window.</p>
                        <button type="button" onClick={checkGoogleWindow}>
                          I finished Google sign-in
                        </button>
                        <button type="button" onClick={cancelGoogle}>
                          Cancel
                        </button>
                      </div>
                    )}
                  </>
                ) : displayedStep === "password" ? (
                  <>
                    <form className={styles.form} onSubmit={submitPassword}>
                      <button
                        type="button"
                        className={styles.textButton}
                        disabled={pending}
                        onClick={() => {
                          setStep("email");
                          setShowPassword(false);
                          setError("");
                        }}
                      >
                        <ArrowLeft size={15} /> Other sign-in options
                      </button>
                      <label htmlFor="account-password-email">
                        Email address
                      </label>
                      <div className={styles.inputWrap}>
                        <Mail size={18} aria-hidden="true" />
                        <input
                          id="account-password-email"
                          autoCapitalize="none"
                          spellCheck={false}
                          type="email"
                          autoComplete="username"
                          value={email}
                          onChange={(event) => setEmail(event.target.value)}
                          maxLength={320}
                          required
                          disabled={pending}
                        />
                      </div>
                      <label htmlFor="account-password">Password</label>
                      <div className={styles.inputWrap}>
                        <input
                          id="account-password"
                          ref={passwordRef}
                          type={showPassword ? "text" : "password"}
                          autoComplete="current-password"
                          required
                          disabled={pending}
                        />
                        <button
                          type="button"
                          className={styles.reveal}
                          aria-label={
                            showPassword ? "Hide password" : "Show password"
                          }
                          aria-pressed={showPassword}
                          onClick={() => setShowPassword((visible) => !visible)}
                          disabled={pending}
                        >
                          {showPassword ? (
                            <EyeOff size={18} aria-hidden="true" />
                          ) : (
                            <Eye size={18} aria-hidden="true" />
                          )}
                        </button>
                      </div>
                      <button
                        type="submit"
                        className={styles.primary}
                        disabled={pending || preview}
                      >
                        {pending ? "Signing in…" : "Sign in"}
                        <ArrowRight
                          size={18}
                          aria-hidden="true"
                          className={styles.arrow}
                        />
                      </button>
                    </form>
                    {!selectedFile &&
                      (learnerLinks.forgotPasswordHref ||
                        learnerLinks.registerHref) && (
                        <div className={styles.passwordLinks}>
                          {learnerLinks.forgotPasswordHref ? (
                            <a href={learnerLinks.forgotPasswordHref}>
                              Forgot your password?
                            </a>
                          ) : null}
                          {learnerLinks.registerHref ? (
                            <a href={learnerLinks.registerHref}>
                              Create a learner account
                            </a>
                          ) : null}
                        </div>
                      )}
                  </>
                ) : (
                  <form className={styles.form} onSubmit={verify}>
                    <button
                      type="button"
                      className={styles.textButton}
                      disabled={pending || preview}
                      onClick={() => {
                        setStep("email");
                        setError("");
                        setSessionCheckNeeded(false);
                      }}
                    >
                      <ArrowLeft size={15} />
                      Change email
                    </button>
                    <label htmlFor="account-code">Sign-in code</label>
                    <input
                      ref={codeRef}
                      id="account-code"
                      className={styles.code}
                      name="code"
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      pattern="[0-9]{6}"
                      onInput={(event) => {
                        event.currentTarget.value = event.currentTarget.value
                          .replace(/\D/g, "")
                          .slice(0, 6);
                      }}
                      required
                      disabled={pending || preview}
                      aria-describedby="code-help"
                    />
                    <p id="code-help" className={styles.codeHelp}>
                      {expired
                        ? "This code has expired. Request a new one below."
                        : "You can paste the complete code from your email."}
                    </p>
                    <button
                      type="submit"
                      className={styles.primary}
                      disabled={pending || expired || preview}
                    >
                      {pending ? (
                        <>
                          <LoaderCircle className={styles.spin} size={18} />
                          Verifying…
                        </>
                      ) : (
                        <>
                          Verify and continue
                          <ArrowRight size={18} className={styles.arrow} />
                        </>
                      )}
                    </button>
                    {sessionCheckNeeded && (
                      <button
                        type="button"
                        className={styles.resend}
                        disabled={pending || preview}
                        onClick={() => void checkVerifiedSession()}
                      >
                        Check sign-in status
                      </button>
                    )}
                    <button
                      type="button"
                      className={styles.resend}
                      disabled={pending || seconds > 0 || preview}
                      onClick={() => void sendCode()}
                    >
                      {seconds > 0
                        ? `Resend code in ${seconds}s`
                        : "Resend code"}
                    </button>
                  </form>
                )}
              </>
            )}
            {selectedFile && (
              <div className={styles.file}>
                <FileAudio
                  className={styles.fileIcon}
                  size={22}
                  aria-hidden="true"
                />
                <span className={styles.fileDetails}>
                  <strong title={selectedFile.name}>{selectedFile.name}</strong>
                  <small className={styles.fileStatus}>
                    Ready on this device · not uploaded yet
                  </small>
                </span>
                <AudioLines
                  className={styles.fileWave}
                  size={21}
                  aria-hidden="true"
                />
              </div>
            )}
            <div className={styles.cardFoot}>
              {displayedStep === "email" && !unavailable && (
                <button
                  type="button"
                  className={styles.password}
                  disabled={pending || preview || !interactive}
                  onClick={() => {
                    setStep("password");
                    setError("");
                  }}
                >
                  Use my existing password
                </button>
              )}
              <p className={styles.footnote}>
                {selectedFile
                  ? "Your recording stays here while you sign in."
                  : "The same account works across Authority Closers."}
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
