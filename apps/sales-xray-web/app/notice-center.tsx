"use client";

import {
  AlertCircle,
  BellRing,
  Bug,
  CheckCircle2,
  Copy,
  ExternalLink,
  Info,
  RotateCw,
  X,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import {
  installReportShortcut,
  openBugReport,
  useReporterAvailable,
} from "./bug-report/open";
import { installErrorRecorder, recordError } from "./bug-report/recent-errors";
import {
  AlertHost,
  clearAlert,
  NORMAL_ALERT_MS,
  useNormalAlert,
  type AppAlert,
} from "./ui/alerts";
import styles from "./notice-center.module.css";

/** "work" and "due" are work alerts (ui/alerts.tsx); "due" is within the hour. */
export type NoticeTone = "error" | "info" | "success" | "work" | "due";
export type Notice = Readonly<{
  id: string;
  tone: NoticeTone;
  title: string;
  message?: string;
  /** A request reference the AC team can trace; shown short, copied in full. */
  reference?: string;
  /** "retry" by default; "open" for a way to another app or site; "none". */
  action?: Readonly<{
    label: string;
    run: () => void;
    icon?: "retry" | "open" | "none";
    /** A page in the app to open with it. */
    href?: string;
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

const ICON = {
  error: AlertCircle,
  info: Info,
  success: CheckCircle2,
  work: BellRing,
  due: BellRing,
};

/** A work alert (ui/alerts.tsx) as a corner card: one notification system,
    so it gets the page's room and the fold like every card (owner via the
    orchestrator, 31 Oct 2026: no banner over the top of the page). */
function fromAlert(alert: AppAlert): Notice {
  const action = alert.action;
  return {
    id: `alert:${alert.id}`,
    tone: alert.emphasis === "urgent" ? "due" : "work",
    title: alert.title,
    message: alert.message,
    action: action
      ? {
          label: action.label,
          run: () => action.run?.(),
          href: action.href,
          icon: "none",
        }
      : undefined,
    timeout: alert.timeout ?? NORMAL_ALERT_MS,
    noReport: true,
  };
}

/** Under the pointer or holding keyboard focus: a card waits for it. */
function inUse(node: HTMLElement | null): boolean {
  if (!node) return false;
  try {
    if (node.matches(":hover")) return true;
  } catch {
    // A browser without :hover in matches: focus alone decides.
  }
  return node.contains(document.activeElement);
}

function CardAction({
  action,
  onRun,
}: {
  action: NonNullable<Notice["action"]>;
  onRun: () => void;
}) {
  const icon =
    action.icon === "none" ? null : action.icon === "open" ? (
      <ExternalLink size={13} aria-hidden="true" />
    ) : (
      <RotateCw size={13} aria-hidden="true" />
    );
  const run = () => {
    onRun();
    action.run();
  };
  return action.href ? (
    <Link className={styles.action} href={action.href} onClick={run}>
      {icon}
      {action.label}
    </Link>
  ) : (
    <button type="button" className={styles.action} onClick={run}>
      {icon}
      {action.label}
    </button>
  );
}

function NoticeCard({
  notice,
  leave,
}: {
  notice: Notice;
  /** How the card goes away; by default it leaves the notice list. */
  leave?: () => void;
}) {
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
  const remove = useCallback(
    () => (leave ? leave() : dismissNotice(notice.id)),
    [leave, notice.id],
  );
  const dismiss = async () => {
    if (dismissing) return;
    setDismissing(true);
    setDismissFailed(false);
    try {
      await notice.onDismiss?.();
      forgetSeen(key);
      remove();
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
    let timer = 0;
    // Never from under the pointer or keyboard focus; it tries again shortly.
    const go = () => {
      if (inUse(card.current)) {
        timer = window.setTimeout(go, 2000);
        return;
      }
      remove();
    };
    timer = window.setTimeout(go, timeout);
    return () => window.clearTimeout(timer);
  }, [notice, remove]);
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
      if (!moved && inUse(node)) {
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
      <div ref={card} className={styles.pill} data-tone={notice.tone}>
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
              <CardAction
                action={notice.action}
                onRun={() => {
                  if (!notice.onDismiss) remove();
                }}
              />
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
                  remove();
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

/** The open modal dialog on top (a sheet), or none. */
function topModal(): HTMLDialogElement | null {
  const open = document.querySelectorAll<HTMLDialogElement>("dialog[open]");
  for (let index = open.length - 1; index >= 0; index -= 1) {
    try {
      if (open[index].matches(":modal")) return open[index];
    } catch {
      return null;
    }
  }
  return null;
}

/**
 * While a sheet or dialog is open everything outside it is inert and under
 * it, so a card raised from inside it went unseen (orchestrator, 1 Nov 2026).
 * The stack follows the sheet on top.
 */
function useTopModal(): HTMLDialogElement | null {
  const [modal, setModal] = useState<HTMLDialogElement | null>(null);
  useEffect(() => {
    let timer = 0;
    const look = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setModal(topModal()), 0);
    };
    look();
    const observer = new MutationObserver(look);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["open"],
    });
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
  }, []);
  return modal;
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
  const [stack, setStack] = useState<HTMLDivElement | null>(null);
  const sheet = useTopModal();
  const work = useNormalAlert();
  const workCard = useMemo(() => (work ? fromAlert(work) : null), [work]);
  const workGone = useCallback(() => {
    if (work) clearAlert(work.id);
  }, [work]);

  // The page keeps room for the stack, so content scrolls clear of it: the
  // band from the stack's top to the window's bottom, which the shell adds to
  // the end of the page (shell/lightbox-shell.module.css). No card, no room.
  useEffect(() => {
    const node = stack;
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
  }, [stack]);

  // Inside a sheet the stack is a popover on its top layer (as the picker is),
  // so its cards show and answer taps. It sits above the sheet's footer, so
  // Save stays in sight, and the sheet's words keep room to scroll clear of
  // it (kit sheet: data-sheet-footer, data-sheet-body, --sx-sheet-room).
  useEffect(() => {
    if (!sheet || !stack) return;
    try {
      if (!stack.matches(":popover-open")) stack.showPopover();
    } catch {
      // Without popovers it still sits inside the sheet, over its panel.
    }
    const across = (a: DOMRect, b: DOMRect) =>
      a.left < b.right && b.left < a.right;
    let body: HTMLElement | null = null;
    const place = () => {
      const footer = sheet.querySelector<HTMLElement>("[data-sheet-footer]");
      const edge = footer?.getBoundingClientRect();
      if (
        edge &&
        edge.height > 0 &&
        across(stack.getBoundingClientRect(), edge)
      )
        stack.style.setProperty(
          "--sx-stack-lift",
          `${Math.ceil(window.innerHeight - edge.top + 8)}px`,
        );
      else stack.style.removeProperty("--sx-stack-lift");
      body?.style.removeProperty("--sx-sheet-room");
      body = sheet.querySelector<HTMLElement>("[data-sheet-body]");
      if (!body) return;
      const box = stack.getBoundingClientRect();
      const words = body.getBoundingClientRect();
      const room =
        box.height > 0 && across(box, words)
          ? Math.ceil(words.bottom - box.top + 12)
          : 0;
      if (room > 0) body.style.setProperty("--sx-sheet-room", `${room}px`);
    };
    place();
    const sized =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    sized?.observe(stack);
    const changed = new MutationObserver(place);
    changed.observe(sheet, { childList: true, subtree: true });
    window.addEventListener("resize", place);
    return () => {
      sized?.disconnect();
      changed.disconnect();
      window.removeEventListener("resize", place);
      body?.style.removeProperty("--sx-sheet-room");
      stack.style.removeProperty("--sx-stack-lift");
    };
  }, [sheet, stack]);

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
  // The newest first: a card arrives at the top of the stack, so the cards
  // already there never move (orchestrator, 1 Nov 2026: a card joining below
  // lifted the others, a layout shift); older ones wait under "+N more".
  const shownList = [...(expanded ? list : list.slice(-SHOWN))].reverse();

  return (
    <>
      {/* One corner, under nothing: never over the page header or the top bar
          (owner via the orchestrator, 31 Oct 2026). Work that needs the seller
          rides at its top (ui/alerts.tsx); a new card arrives at the top too.
          It never covers content either: the page keeps room for it, and a card
          folds to a pill once seen (31 Oct 2026). */}
      {/* Inside an open sheet, on its top layer; otherwise in the page. */}
      <StackHost sheet={sheet}>
        <div
          key={sheet ? "sheet" : "page"}
          ref={setStack}
          className={styles.stack}
          aria-live="polite"
          data-capture-skip=""
          popover={sheet ? "manual" : undefined}
        >
          {workCard ? (
            <NoticeCard key={workCard.id} notice={workCard} leave={workGone} />
          ) : null}
          {shownList.map((notice) => (
            <NoticeCard key={notice.id} notice={notice} />
          ))}
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
        </div>
      </StackHost>
      {/* Urgent work: a centre card over the page, by design. */}
      <AlertHost />
    </>
  );
}

function StackHost({
  sheet,
  children,
}: {
  sheet: HTMLDialogElement | null;
  children: ReactNode;
}) {
  return sheet ? createPortal(children, sheet) : children;
}
