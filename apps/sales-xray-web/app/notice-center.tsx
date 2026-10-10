"use client";

import {
  AlertCircle,
  CheckCircle2,
  Copy,
  Info,
  RotateCw,
  X,
} from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";

import styles from "./notice-center.module.css";

export type NoticeTone = "error" | "info" | "success";
export type Notice = Readonly<{
  id: string;
  tone: NoticeTone;
  title: string;
  message?: string;
  /** A request reference the AC team can trace; shown short, copied in full. */
  reference?: string;
  action?: Readonly<{ label: string; run: () => void }>;
  /** Milliseconds before it leaves by itself; errors stay until dismissed. */
  timeout?: number;
  /** Permanent dismissal: retain the card until the API acknowledges it. */
  onDismiss?: () => Promise<void>;
}>;

let notices: readonly Notice[] = [];
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

/** Show a small card in the corner. A repeated id replaces the older card. */
export function notify(notice: Notice) {
  notices = [...notices.filter((item) => item.id !== notice.id), notice].slice(
    -3,
  );
  emit();
}

export function dismissNotice(id: string) {
  notices = notices.filter((item) => item.id !== id);
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const EMPTY: readonly Notice[] = [];

const ICON = { error: AlertCircle, info: Info, success: CheckCircle2 };

function NoticeCard({ notice }: { notice: Notice }) {
  const [copied, setCopied] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [dismissFailed, setDismissFailed] = useState(false);
  const Icon = ICON[notice.tone];
  const dismiss = async () => {
    if (dismissing) return;
    setDismissing(true);
    setDismissFailed(false);
    try {
      await notice.onDismiss?.();
      dismissNotice(notice.id);
    } catch {
      setDismissFailed(true);
      setDismissing(false);
    }
  };
  useEffect(() => {
    const timeout =
      notice.timeout ?? (notice.tone === "error" ? undefined : 5000);
    if (!timeout || notice.onDismiss) return;
    const timer = window.setTimeout(() => dismissNotice(notice.id), timeout);
    return () => window.clearTimeout(timer);
  }, [notice]);
  return (
    <div
      className={styles.card}
      data-tone={notice.tone}
      role={notice.tone === "error" ? "alert" : "status"}
    >
      <Icon className={styles.icon} size={18} aria-hidden="true" />
      <div className={styles.body}>
        <p className={styles.title}>{notice.title}</p>
        {notice.message ? (
          <p className={styles.message}>{notice.message}</p>
        ) : null}
        {notice.action || notice.reference ? (
          <div className={styles.actions}>
            {notice.action ? (
              <button
                type="button"
                className={styles.action}
                onClick={() => {
                  if (!notice.onDismiss) dismissNotice(notice.id);
                  notice.action?.run();
                }}
              >
                <RotateCw size={13} aria-hidden="true" />
                {notice.action.label}
              </button>
            ) : null}
            {notice.reference ? (
              <button
                type="button"
                className={styles.reference}
                title={`Copy reference ${notice.reference}`}
                onClick={() => {
                  void navigator.clipboard
                    ?.writeText(notice.reference ?? "")
                    .then(() => setCopied(true))
                    .catch(() => {});
                }}
              >
                <Copy size={12} aria-hidden="true" />
                {copied ? "Copied" : `Ref ${notice.reference.slice(0, 8)}`}
              </button>
            ) : null}
          </div>
        ) : null}
        {dismissFailed ? (
          <p role="alert">Could not dismiss. Try again.</p>
        ) : null}
      </div>
      <button
        type="button"
        className={styles.close}
        aria-label="Dismiss"
        disabled={dismissing}
        onClick={() => void dismiss()}
      >
        <X size={15} aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * The one place app-level problems appear: a small stack of cards in the
 * bottom corner (above the tab bar on phones). It also catches unexpected
 * script failures so they never surface as a developer panel.
 */
export function NoticeCenter() {
  const list = useSyncExternalStore(
    subscribe,
    () => notices,
    () => EMPTY,
  );

  useEffect(() => {
    let last = 0;
    const glitch = () => {
      // One card per burst; an error loop must not flood the screen.
      const now = Date.now();
      if (now - last < 4000) return;
      last = now;
      notify({
        id: "unexpected",
        tone: "error",
        title: "Something glitched on this screen",
        message: "Your calls and reports are safe. Reload to continue.",
        action: { label: "Reload", run: () => window.location.reload() },
      });
    };
    const onError = (event: ErrorEvent) => {
      // Resource and cross-origin script noise carry no error object.
      if (event.error) glitch();
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason as { name?: string } | null;
      if (reason?.name === "AbortError") return;
      glitch();
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  return (
    <div className={styles.stack} aria-live="polite">
      {list.map((notice) => (
        <NoticeCard key={notice.id} notice={notice} />
      ))}
    </div>
  );
}
