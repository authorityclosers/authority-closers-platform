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
  type CSSProperties,
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
  popupHostileBrowser,
  providerEnabled,
  providerLabel,
  readCanonicalSession,
  readGoogleCompletion,
  forgetSignInResult,
  readSignInResult,
  rememberRedirectSignIn,
  type AuthCompletionResult,
  type EmailCodeConfig,
  type SignInProvider,
} from "./account-auth-client";
import styles from "./account-auth.module.css";
import { inPhoneApp, phoneStatus } from "./leads/native-phone";

export type AccountAuthPreviewState = "auth.email" | "auth.code" | "auth.error";

const PREVIEW_CONFIG: EmailCodeConfig = {
  enabled: true,
  consent_version: "review-only",
  google_enabled: true,
  apple_enabled: true,
  facebook_enabled: true,
  expires_in_seconds: 600,
  resend_after_seconds: 60,
};
// The order the sign-in screen offers them in (owner, 19 Oct 2026).
const PROVIDERS = ["google", "apple", "facebook"] as const;
// Decorative "x-ray" of a conversation: a scan passes over a two-speaker
// waveform and the kinds of moment Sales Xray looks for light up. It shows no
// data; heights are a fixed pattern so server and client render the same.
const XRAY_BAR_COUNT = 64;
const XRAY_SWEEP_SECONDS = 7;
const XRAY_BARS = Array.from({ length: XRAY_BAR_COUNT }, (_, index) => {
  const envelope = Math.abs(Math.sin(index * 0.21) * Math.cos(index * 0.047));
  const grain = ((index * 37) % 11) / 11;
  return Math.round(16 + 74 * (0.3 + 0.7 * envelope) * (0.62 + 0.38 * grain));
});
const XRAY_SPEAKER_TURNS = [0, 12, 23, 37, 47] as const;
const XRAY_MOMENTS = [
  { kind: "strength", label: "Strong moment", from: 16, to: 19, row: 0 },
  { kind: "objection", label: "Objection", from: 28, to: 31, row: 1 },
  { kind: "missed", label: "Missed opportunity", from: 40, to: 43, row: 0 },
  { kind: "next", label: "Next step", from: 55, to: 58, row: 1 },
] as const;
const XRAY_FEATURES = [
  { Icon: UsersRound, label: "Speakers separated" },
  { Icon: Sparkles, label: "Moments and objections" },
  { Icon: FileText, label: "A clear summary" },
] as const;

function xrayDelay(position: number) {
  return `${((position + 0.5) / XRAY_BAR_COUNT) * XRAY_SWEEP_SECONDS}s`;
}

function xraySpeaker(index: number) {
  return XRAY_SPEAKER_TURNS.filter((turn) => turn <= index).length % 2 === 1
    ? "rep"
    : "buyer";
}

function xrayMoment(index: number) {
  return XRAY_MOMENTS.find(
    (moment) => index >= moment.from && index <= moment.to,
  );
}

function XrayScene() {
  return (
    <div className={`${styles.xray} sx-web-only`} aria-hidden="true">
      {XRAY_MOMENTS.map((moment) => (
        <span
          key={moment.kind}
          className={styles.tag}
          data-kind={moment.kind}
          data-row={moment.row}
          style={
            {
              "--x": `${(((moment.from + moment.to) / 2 + 0.5) / XRAY_BAR_COUNT) * 100}%`,
              "--d": xrayDelay(moment.from),
            } as CSSProperties
          }
        >
          <i />
          {moment.label}
        </span>
      ))}
      <div className={styles.track}>
        {XRAY_BARS.map((height, index) => {
          const moment = xrayMoment(index);
          return (
            <span
              key={index}
              className={styles.bar}
              data-speaker={xraySpeaker(index)}
              data-kind={moment?.kind}
              style={
                {
                  "--h": `${height}%`,
                  "--d": xrayDelay(index),
                } as CSSProperties
              }
            />
          );
        })}
        <span className={styles.beamRail}>
          <span className={styles.beam} />
        </span>
      </div>
    </div>
  );
}

// Google sign-in cannot finish on the dev site until dev has its own sign-in
// server (AUT-157): Google returns to staging, which cannot see the dev start.
const DEV_HOST = "salesxray-dev.authorityclosers.com";
const noHostSubscription = () => () => {};
// 11 Oct: dev now has its own sign-in back end (dev-live API, dev Google OAuth client), so Google works on dev too.
const readGoogleBlocked = () => false && window.location.hostname === DEV_HOST;

function GoogleMark() {
  // Google's own four-colour "G", as its sign-in branding requires.
  return (
    <svg
      className={styles.providerMark}
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
function AppleMark() {
  // Apple's logo, as Sign in with Apple's button guidelines require.
  return (
    <svg
      className={styles.providerMark}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="currentColor"
        d="M16.37 1.43c0 1.14-.49 2.27-1.18 3.08-.74.9-1.99 1.57-2.99 1.57-.12 0-.23-.02-.3-.03-.01-.06-.04-.22-.04-.39 0-1.15.57-2.27 1.21-2.98.8-.94 2.14-1.64 3.25-1.68.03.13.05.28.05.43Zm4.56 15.71c-.03.07-.46 1.58-1.52 3.12-.94 1.34-1.94 2.71-3.43 2.71-1.52 0-1.9-.88-3.63-.88-1.7 0-2.3.91-3.67.91-1.38 0-2.33-1.26-3.43-2.8-1.29-1.82-2.32-4.63-2.32-7.28 0-4.28 2.8-6.55 5.55-6.55 1.45 0 2.68.95 3.6.95.87 0 2.22-1.01 3.9-1.01.61 0 2.89.06 4.37 2.19-.13.09-2.38 1.37-2.38 4.19 0 3.26 2.85 4.42 2.96 4.45Z"
      />
    </svg>
  );
}

function FacebookMark() {
  // Facebook's "f" mark in Facebook blue, as its brand rules require.
  return (
    <svg
      className={styles.providerMark}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="#1877F2"
        d="M9.1 23.69v-7.98H6.63v-3.67H9.1v-1.58c0-4.09 1.85-5.98 5.86-5.98.4 0 .96.04 1.47.1.41.05.81.11 1.14.2v3.32a8.6 8.6 0 0 0-.65-.03c-.24-.01-.48-.01-.73-.01-.71 0-1.26.1-1.68.31-.28.14-.52.36-.68.62-.26.42-.37 1-.37 1.75v1.3h3.92l-.39 2.1-.29 1.57h-3.24v8.24C19.4 23.24 24 18.18 24 12.04 24 5.42 18.63.04 12 .04S0 5.42 0 12.04c0 5.63 3.87 10.35 9.1 11.65Z"
      />
    </svg>
  );
}

const PROVIDER_MARKS = {
  google: GoogleMark,
  apple: AppleMark,
  facebook: FacebookMark,
} as const;

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

/** What a finished sign-in that did not sign the person in should say. */
export function signInProblem(
  result: Exclude<AuthCompletionResult, "success">,
  provider: SignInProvider,
) {
  const label = providerLabel(provider);
  if (result === "account_exists")
    return "This email already has an Authority Closers account. Sign in the way you did before, or with your password or an email code.";
  if (result === "no_email")
    return `${label} didn’t share your email address. Allow email access, or choose another way to sign in.`;
  if (result === "review_terms")
    return "Review the current Terms and Privacy notice, then try signing in again.";
  if (result === "unavailable")
    return `${label} sign-in is unavailable right now. Try again or use an email code.`;
  return `${label} sign-in could not be completed. Try again or use an email code.`;
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
  // A full-page sign-in is under way (the sign-in window was blocked).
  const [redirecting, setRedirecting] = useState<SignInProvider | null>(null);
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
  const popupProvider = useRef<SignInProvider>("google");
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
  const finish = useRef<() => void>(() => {});
  useEffect(() => {
    finish.current = complete;
  });
  useEffect(() => {
    if (preview) return;
    // Back from a full-page sign-in: the completion page already matched this
    // flow's receipt; read the account session again before finishing.
    // Read now, forget once used: development runs this effect twice.
    const returned = readSignInResult();
    if (!returned) return;
    const request = new AbortController();
    void Promise.resolve().then(async () => {
      if (request.signal.aborted) return;
      forgetSignInResult();
      if (returned.result !== "success") {
        if (returned.result === "review_terms")
          setLoadAttempt((value) => value + 1);
        setError(signInProblem(returned.result, returned.provider));
        return;
      }
      inFlight.current = true;
      setPending(true);
      try {
        await readCanonicalSession(request.signal);
        if (!request.signal.aborted) finish.current();
      } catch {
        if (!request.signal.aborted)
          setError(
            `${providerLabel(returned.provider)} sign-in could not be confirmed. Try again or use an email code.`,
          );
      } finally {
        inFlight.current = false;
        if (!request.signal.aborted) setPending(false);
      }
    });
    return () => request.abort();
  }, [preview]);
  useEffect(() => {
    if (!redirecting) return;
    // Still here: the page came back from the back-forward cache, or the
    // phone app opened the sign-in in its browser and the person returned.
    const reset = () => {
      inFlight.current = false;
      setPending(false);
      setRedirecting(null);
    };
    const shown = (event: PageTransitionEvent) => {
      if (event.persisted) reset();
    };
    const visible = () => {
      if (document.visibilityState === "visible") reset();
    };
    window.addEventListener("pageshow", shown);
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.removeEventListener("pageshow", shown);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [redirecting]);
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
          `${providerLabel(popupProvider.current)} sign-in could not be confirmed. Try again or use an email code.`,
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
    }
    setError(signInProblem(result, popupProvider.current));
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
          `${providerLabel(popupProvider.current)} sign-in could not be confirmed. Try again or use an email code.`,
        );
        return;
      }
    } catch {
      // The provider page remains cross-origin until it returns here.
    }
    setError(
      `Finish sign-in in the ${providerLabel(popupProvider.current)} window, then check again.`,
    );
  }

  function startProvider(provider: SignInProvider) {
    if (
      preview ||
      !activeConfig ||
      !providerEnabled(activeConfig, provider) ||
      configError ||
      !consent ||
      inFlight.current
    )
      return;
    const label = providerLabel(provider);
    // In the phone app only Google has the app's own sign-in window; Apple and
    // Facebook go through this page, which the app opens in the phone's browser.
    const appBrowser = provider !== "google" && inPhoneApp();
    // Open a blank same-origin popup synchronously. Fresh policy is checked
    // before navigating it to Google, while the File stays in this document.
    // Where the window is blocked (the Claude desktop pane) or breaks (in-app
    // browsers), the same click signs in on this page instead.
    const flow = crypto.randomUUID();
    const opened =
      appBrowser || popupHostileBrowser(navigator.userAgent)
        ? null
        : window.open(
            "about:blank",
            "sales-xray-sign-in",
            "popup,width=520,height=720",
          );
    const child = opened && !opened.closed ? opened : null;
    if (child) {
      popup.current = child;
      popupFlow.current = flow;
      popupOutcome.current = null;
      popupProvider.current = provider;
      setPopupActive(true);
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
        setError(`${label} sign-in timed out. Try again or use an email code.`);
      }, 5 * 60_000);
    }
    inFlight.current = true;
    setPending(true);
    setError("");
    const request = new AbortController();
    controller.current = request;
    void emailCodeRequest("config", request.signal)
      .then(parseEmailCodeConfig)
      .then(async (current) => {
        if (request.signal.aborted) return;
        setConfig(current);
        if (
          !providerEnabled(current, provider) ||
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
        const start = `/v1/auth/${provider}/start?${parameters}`;
        if (child) {
          child.location.assign(start);
          return;
        }
        if (appBrowser && !(await phoneStatus())?.signIn) {
          inFlight.current = false;
          setPending(false);
          setError(
            `Update the Sales Xray app to sign in with ${label}, or use Google or an email code.`,
          );
          return;
        }
        if (request.signal.aborted) return;
        // Without storage the completion page still signs in and goes home.
        rememberRedirectSignIn(
          flow,
          provider,
          window.location.pathname + window.location.search,
        );
        setRedirecting(provider);
        window.location.assign(new URL(start, window.location.origin).href);
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
  const offered = (provider: SignInProvider) =>
    (provider !== "google" || !googleBlocked) &&
    providerEnabled(activeConfig, provider) &&
    !configError &&
    !(preview && previewState === "auth.error");
  const offeredProviders = PROVIDERS.filter(offered);
  const googleAvailable = offeredProviders.length > 0;
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
      "One quick step for new and returning members."
    );
  return (
    <section
      className={`xray-app ${styles.auth}`}
      aria-labelledby="account-auth-heading"
      aria-busy={pending}
      data-review-preview={preview ? "true" : undefined}
    >
      <div className={styles.stage}>
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
        {/* The marketing story is website chrome: the phone app shows
            only the brand above the form (in-app.ts). */}
        <div className={`${styles.storyCopy} sx-web-only`}>
          <h2>
            Hear the <span className={styles.accent}>opportunity</span>
            <br />
            in every call.
          </h2>
          <p>Bring your conversation. Leave with a clearer next step.</p>
        </div>
        <XrayScene />
        <ul className={`${styles.features} sx-web-only`}>
          {XRAY_FEATURES.map(({ Icon, label }) => (
            <li key={label}>
              <Icon size={16} aria-hidden="true" />
              {label}
            </li>
          ))}
        </ul>
        <p className={`${styles.shared} sx-web-only`}>
          <ShieldCheck size={15} aria-hidden="true" />
          One AC account. Your learning, calls and reports.
        </p>
      </div>
      <div className={styles.formColumn}>
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
            <Link className={`${styles.returnLink} sx-web-only`} href="/">
              <ArrowLeft size={16} aria-hidden="true" /> Return to app
            </Link>
          ) : (
            <span />
          )}
          <span className={styles.themeSlot}>
            <ThemeToggle />
          </span>
        </div>
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
                      for my Authority Closers account.
                    </span>
                  </label>
                  {googleBlocked ? (
                    <p className={styles.consentHint}>
                      Google sign-in is not available on the dev site yet. Use
                      an email code, or your password.
                    </p>
                  ) : null}
                  {googleAvailable && (
                    <div className={styles.providers}>
                      {offeredProviders.map((provider) => {
                        const Mark = PROVIDER_MARKS[provider];
                        return (
                          <button
                            key={provider}
                            type="button"
                            className={styles.google}
                            data-provider={provider}
                            onClick={() => startProvider(provider)}
                            disabled={preview || !consent || pending}
                            aria-describedby={
                              !consent
                                ? "account-google-consent-hint"
                                : undefined
                            }
                          >
                            <Mark />
                            Continue with {providerLabel(provider)}
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {googleAvailable && !consent && (
                    <p
                      id="account-google-consent-hint"
                      className={styles.consentHint}
                    >
                      Tick the box above to continue with{" "}
                      {offeredProviders.map(providerLabel).join(", ")} or email.
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
                        <label
                          htmlFor="account-email"
                          className={styles.visuallyHidden}
                        >
                          Email address
                        </label>
                        <div className={styles.inputWrap}>
                          <Mail size={18} aria-hidden="true" />
                          <input
                            id="account-email"
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
                        <button
                          type="submit"
                          className={styles.primary}
                          disabled={
                            preview || !available || !consent || pending
                          }
                        >
                          {pending ? (
                            <>
                              <LoaderCircle className={styles.spin} size={18} />
                              Sending…
                            </>
                          ) : (
                            <>
                              Send sign-in code
                              <ArrowRight size={18} className={styles.arrow} />
                            </>
                          )}
                        </button>
                      </>
                    )}
                  </form>
                  {redirecting && pending && (
                    <div className={styles.popupActions} role="status">
                      <p>Opening {providerLabel(redirecting)} sign-in…</p>
                    </div>
                  )}
                  {popupActive && pending && (
                    <div className={styles.popupActions} role="status">
                      <p>
                        Finish sign-in in the{" "}
                        {providerLabel(popupProvider.current)} window.
                      </p>
                      <button type="button" onClick={checkGoogleWindow}>
                        I finished {providerLabel(popupProvider.current)}{" "}
                        sign-in
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
                  {!selectedFile && (
                    <div className={styles.passwordLinks}>
                      {learnerLinks.forgotPasswordHref ? (
                        <a href={learnerLinks.forgotPasswordHref}>
                          Forgot your password?
                        </a>
                      ) : (
                        <p>
                          Reset your password in the Authority Closers learning
                          app.
                        </p>
                      )}
                      {learnerLinks.registerHref ? (
                        <a href={learnerLinks.registerHref}>
                          Create a learner account
                        </a>
                      ) : (
                        <p>
                          Create your learner account in the Authority Closers
                          learning app.
                        </p>
                      )}
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
                    {seconds > 0 ? `Resend code in ${seconds}s` : "Resend code"}
                  </button>
                </form>
              )}
              <p
                ref={errorRef}
                tabIndex={-1}
                role={error ? "alert" : undefined}
                className={styles.error}
              >
                {error}
                {error ? (
                  <button
                    type="button"
                    className={styles.errorClose}
                    aria-label="Dismiss"
                    onClick={() => setError("")}
                  >
                    ×
                  </button>
                ) : null}
              </p>
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
              <svg
                className={styles.footnoteIcon}
                viewBox="0 0 16 16"
                aria-hidden="true"
              >
                <path
                  d="M8 1.5 2.5 4v3.6c0 3.2 2.3 5.9 5.5 6.9 3.2-1 5.5-3.7 5.5-6.9V4L8 1.5Z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.3"
                  strokeLinejoin="round"
                />
                <path
                  d="m5.6 8 1.7 1.7 3.2-3.4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span>
                {selectedFile ? (
                  "Your recording stays here while you sign in."
                ) : (
                  <>
                    One account for <strong>every Authority Closers app</strong>
                  </>
                )}
              </span>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
