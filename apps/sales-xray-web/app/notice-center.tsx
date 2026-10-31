"use client";

import {
  AlertCircle,
  Bug,
  CheckCircle2,
  Copy,
  ExternalLink,
  Info,
  RotateCw,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  installReportShortcut,
  openBugReport,
  useReporterAvailable,
} from "./bug-report/open";
import { installErrorRecorder, recordError } from "./bug-report/recent-errors";
import { AlertHost } from "./ui/alerts";
import styles from "./notice-center.module.css";

export type NoticeTone = "error" | "info" | "success";
export type Notice = Readonly<{
  id: string;
  tone: NoticeTone;
  title: string;
  message?: string;
  /** A request reference the AC team can trace; shown short, copied in full. */
  reference?: string;
  /** "retry" by default; "open" for a way to another app or site. */
  action?: Readonly<{
    label: string;
    run: () => void;
    icon?: "retry" | "open";
  }>;
  /** Milliseconds before it leaves by itself; errors stay until dismissed. */
  timeout?: number;
  /** A worded dismiss beside the action ("Later"); it dismisses like the X. */
  dismissLabel?: string;
  /** Permanent dismissal: retain the card until the API acknowledges it. */
  onDismiss?: () => Promise<void>;
  /** Arrive as the one-line pill: its owner knows it was seen (a tap opens it). */
  folded?: boolean;
  /** The same as folded (the recording card's first name for it). */
  slim?: boolean;
  /** Error cards offer "Report" (the bug reporter); not on the reporter's own. */
  noReport?: boolean;
}>;

/** At most two cards show (owner via the orchestrator, 31 Oct 2026); older ones
    wait under "+N more", up to this many. */
const SHOWN = 2;
const KEPT = 8;

/** A corner card may never cover content (owner via the orchestrator, 31 Oct
    2026): once seen, a card folds to a one-line pill, and a tap opens it. It
    folds after this long, or as soon as the person taps elsewhere or scrolls. */
const FOLD_MS = 8000;
const FOLD_AFTER_MS = 1200;
const SEEN_KEY = "sx.corner.seen";

// Cards seen this visit come back folded (Home to Leads and back), until the
// person closes them; a new title is new news and opens again.
const seenKey = (notice: Notice) => `${notice.id}\n${notice.title}`;
function readSeen(): string[] {
  try {
    const list: unknown = JSON.parse(
      window.sessionStorage.getItem(SEEN_KEY) ?? "[]",
    );
    return Array.isArray(list)
      ? list.filter((item) => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}
function writeSeen(list: string[]) {
  try {
    window.sessionStorage.setItem(SEEN_KEY, JSON.stringify(list.slice(-30)));
  } catch {
    // Without storage a card simply opens again next time.
  }
}
const wasSeen = (key: string) => readSeen().includes(key);
function markSeen(key: string) {
  const list = readSeen();
  if (!list.includes(key)) writeSeen([...list, key]);
}
const forgetSeen = (key: string) =>
  writeSeen(readSeen().filter((item) => item !== key));

let notices: readonly Notice[] = [];
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

/** Show a small card in the corner. A repeated id replaces the older card. */
export function notify(notice: Notice) {
  if (notice.tone === "error") {
    recordError({
      kind: "notice",
      message: [notice.title, notice.message].filter(Boolean).join(": "),
      reference: notice.reference,
    });
  }
  notices = [...notices.filter((item) => item.id !== notice.id), notice].slice(
    -KEPT,
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
  const reporter = useReporterAvailable();
  const report = notice.tone === "error" && !notice.noReport && reporter;
  const [copied, setCopied] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [dismissFailed, setDismissFailed] = useState(false);
  const card = useRef<HTMLDivElement>(null);
  const opened = useRef(false);
  const key = seenKey(notice);
  const arrivesFolded = () =>
    notice.folded === true || notice.slim === true || wasSeen(key);
  const [folded, setFolded] = useState(arrivesFolded);
  const [cardKey, setCardKey] = useState(key);
  if (cardKey !== key) {
    setCardKey(key);
    setFolded(arrivesFolded());
  }
  const Icon = ICON[notice.tone];
  const dismiss = async () => {
    if (dismissing) return;
    setDismissing(true);
    setDismissFailed(false);
    try {
      await notice.onDismiss?.();
      forgetSeen(key);
      dismissNotice(notice.id);
    } catch {
      setDismissFailed(true);
      setDismissing(false);
      setFolded(false);
    }
  };
  useEffect(() => {
    const timeout =
      notice.timeout ?? (notice.tone === "error" ? undefined : 5000);
    if (!timeout || notice.onDismiss) return;
    const timer = window.setTimeout(() => dismissNotice(notice.id), timeout);
    return () => window.clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (folded) return;
    const node = card.current;
    // A pill opened by a tap keeps focus, so it stays open while it's read.
    if (opened.current) {
      opened.current = false;
      node?.focus({ preventScroll: true });
    }
    let timer = 0;
    const fold = (moved: boolean) => {
      // Not under the pointer or keyboard focus; it tries again shortly.
      if (
        !moved &&
        (node?.matches(":hover") || node?.contains(document.activeElement))
      ) {
        timer = window.setTimeout(() => fold(false), 2000);
        return;
      }
      markSeen(key);
      setFolded(true);
    };
    const away = (event: Event) => {
      if (event.target instanceof Node && node?.contains(event.target)) return;
      fold(true);
    };
    timer = window.setTimeout(() => fold(false), FOLD_MS);
    const listen = window.setTimeout(() => {
      document.addEventListener("pointerdown", away, true);
      document.addEventListener("scroll", away, true);
    }, FOLD_AFTER_MS);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(listen);
      document.removeEventListener("pointerdown", away, true);
      document.removeEventListener("scroll", away, true);
    };
  }, [folded, key]);
  if (folded)
    return (
      <div className={styles.pill} data-tone={notice.tone}>
        <button
          type="button"
          className={styles.pillOpen}
          aria-expanded="false"
          onClick={() => {
            opened.current = true;
            setFolded(false);
          }}
        >
          <Icon className={styles.icon} size={16} aria-hidden="true" />
          <span className={styles.pillText}>{notice.title}</span>
        </button>
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
  return (
    <div
      ref={card}
      className={styles.card}
      data-tone={notice.tone}
      role={notice.tone === "error" ? "alert" : "status"}
      tabIndex={-1}
    >
      <Icon className={styles.icon} size={18} aria-hidden="true" />
      <div className={styles.body}>
        <p className={styles.title}>{notice.title}</p>
        {notice.message ? (
          <p className={styles.message}>{notice.message}</p>
        ) : null}
        {notice.action || notice.dismissLabel || notice.reference || report ? (
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
                {notice.action.icon === "open" ? (
                  <ExternalLink size={13} aria-hidden="true" />
                ) : (
                  <RotateCw size={13} aria-hidden="true" />
                )}
                {notice.action.label}
              </button>
            ) : null}
            {notice.dismissLabel ? (
              <button
                type="button"
                className={styles.reference}
                disabled={dismissing}
                onClick={() => void dismiss()}
              >
                {notice.dismissLabel}
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
            {report ? (
              <button
                type="button"
                className={styles.reference}
                onClick={() => {
                  dismissNotice(notice.id);
                  openBugReport({
                    title: notice.title,
                    reference: notice.reference,
                  });
                }}
              >
                <Bug size={12} aria-hidden="true" />
                Report
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
  const [expanded, setExpanded] = useState(false);
  const stack = useRef<HTMLDivElement>(null);

  // The page keeps room for the stack, so content scrolls clear of it: the
  // band from the stack's top to the window's bottom, which the shell adds to
  // the end of the page (shell/lightbox-shell.module.css). No card, no room.
  useEffect(() => {
    const node = stack.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const root = document.documentElement;
    const publish = () => {
      const box = node.getBoundingClientRect();
      if (box.height < 1) root.style.removeProperty("--sx-corner-h");
      else
        root.style.setProperty(
          "--sx-corner-h",
          `${Math.ceil(window.innerHeight - box.top)}px`,
        );
    };
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(node);
    window.addEventListener("resize", publish);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", publish);
      root.style.removeProperty("--sx-corner-h");
    };
  }, []);

  // Keeps the page's last twenty problems for a bug report (bug-report/).
  useEffect(() => installErrorRecorder(), []);
  // Ctrl B or ⌘B reports a problem from anywhere (bug-report/open.ts).
  useEffect(() => installReportShortcut(), []);

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

  const waiting = Math.max(0, list.length - SHOWN);
  // Once no card waits, the next pile starts folded again.
  if (expanded && waiting === 0) setExpanded(false);
  const shownList = expanded ? list : list.slice(-SHOWN);

  return (
    <>
      {/* One corner, under nothing: never over the page header or the top bar
          (owner via the orchestrator, 31 Oct 2026). Work that needs the seller
          rides at its top (ui/alerts.tsx); the newest card sits nearest the corner.
          It never covers content either: the page keeps room for it, and a card
          folds to a pill once seen (31 Oct 2026). */}
      <div
        ref={stack}
        className={styles.stack}
        aria-live="polite"
        data-capture-skip=""
      >
        <AlertHost only="banner" stacked />
        {waiting > 0 ? (
          <button
            type="button"
            className={styles.more}
            aria-expanded={expanded}
            onClick={() => setExpanded((now) => !now)}
          >
            {expanded ? "Show fewer" : `+${waiting} more`}
          </button>
        ) : null}
        {shownList.map((notice) => (
          <NoticeCard key={notice.id} notice={notice} />
        ))}
      </div>
      {/* Urgent work: a centre card over the page, by design. */}
      <AlertHost only="urgent" />
    </>
  );
}
