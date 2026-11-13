"use client";

import {
  AlertCircle,
  BellRing,
  Bug,
  CheckCircle2,
  Copy,
  ExternalLink,
  Info,
  PhoneIncoming,
  RotateCw,
  X,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
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
import { keepEndInView } from "./end-hold";
import { SCREEN_SETTLED_EVENT } from "./shell/screen-transition";
import {
  AlertHost,
  clearAlert,
  NORMAL_ALERT_MS,
  useNormalAlert,
  type AppAlert,
} from "./ui/alerts";
import styles from "./notice-center.module.css";

/** "work" and "due" are work alerts (ui/alerts.tsx); "due" is within the hour;
    "lead" is a new enquiry (competitor teardown 12). */
export type NoticeTone = "error" | "info" | "success" | "work" | "due" | "lead";
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
  /** Its action stays in the one-line pill: "New enquiry · Asha · Meta",
      Call now (competitor teardown 12, 1 Nov 2026). */
  pillAction?: boolean;
  /** Error cards offer "Report" (the bug reporter); not on the reporter's own. */
  noReport?: boolean;
  /** One line in a phone page's dock, as new enquiries and work alerts are. */
  dock?: boolean;
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
// Cards on screen now, folded or not: a card that moves (out of a sheet that
// closed) comes back as it was, without arriving again (phone personas ph2-36,
// 1 Nov 2026: the after-call Undo jumped and vanished).
const placed = new Map<string, boolean>();
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

/** Whether a card with this id is up now: one setup card at a time (Redmi QA
 *  on production, 10 Nov 2026: "Finish setting up" over "Recording isn't set
 *  up" on Home). */
export function useNoticeShown(id: string): boolean {
  return useSyncExternalStore(
    subscribe,
    () => notices.some((item) => item.id === id),
    () => false,
  );
}

const EMPTY: readonly Notice[] = [];

// ----- the dock --------------------------------------------------------------------------

/** New enquiries and work alerts; app problems keep the corner (owner, 31 Oct 2026). */
const DOCKED_TONES: ReadonlySet<NoticeTone> = new Set(["lead", "work", "due"]);
const DOCK_MEDIA = "(max-width: 759.98px)";
let dock: HTMLElement | null = null;
const dockListeners = new Set<() => void>();
function setDock(node: HTMLElement | null) {
  if (dock === node) return;
  dock = node;
  dockListeners.forEach((listener) => listener());
}
function subscribeDock(listener: () => void) {
  dockListeners.add(listener);
  return () => {
    dockListeners.delete(listener);
  };
}
const noDock = () => null;

// Where each line sits on the current dock, decided once, when it first shows:
// true, in the dock; false, in the corner, over the page.
let placedOn: HTMLElement | null = null;
const inDockHere = new Map<string, boolean>();

/** Whether the page under the dock is drawn and in sight, so a line put in
 *  the dock now would push it down. A loading outline is about to go, so a
 *  line landing with the page's first draw still docks (Leads raises its lines
 *  with the answer that draws it, side-numbers.ts). */
function pageShownUnder(node: HTMLElement): boolean {
  if (typeof document.elementFromPoint !== "function") return false;
  // The page is still on its way: the shell draws its outline under the dock
  // (lightbox-shell.tsx), which goes as the page comes.
  if (node.parentElement?.querySelector(":scope > [data-standing-in]"))
    return false;
  const y = node.getBoundingClientRect().bottom + 8;
  if (y >= window.innerHeight) return false;
  const under = document.elementFromPoint(window.innerWidth / 2, y);
  if (!under || node.contains(under)) return false;
  return !under.closest('[aria-busy="true"], [data-standing-in]');
}

/**
 * The dock takes the lines waiting when it is drawn, and later ones while the
 * page under it isn't drawn yet. A line arriving over a drawn page, or under
 * an open sheet, sits in the corner over it instead of pushing it down (QA
 * robot 4b12c389, 3 Nov 2026: "… is your lead now" came 4 to 8 s into Leads
 * Analytics and dropped it 52 px). The next page's dock takes it from its
 * first frame. Read during render: the page as last drawn, before the line.
 */
function placeLines(
  node: HTMLElement | null,
  ids: readonly string[],
  covered: boolean,
) {
  if (node !== placedOn) {
    placedOn = node;
    inDockHere.clear();
    if (node) for (const id of ids) inDockHere.set(id, true);
    return;
  }
  if (!node) return;
  for (const id of ids)
    if (!inDockHere.has(id))
      inDockHere.set(id, !covered && !pageShownUnder(node));
}

/**
 * Where a page puts its new-lead and work notices on a phone: one line in the
 * page above its rows, never over them, their Call buttons or the tab bar
 * (competitor teardown 12; the orchestrator, 1 Nov 2026: "Varun Chauhan is
 * your lead now" covered the second row's Open on Follow-ups at 360 px).
 * Computers keep the corner, which has room beside the page.
 *
 * It takes its lines before the page is first drawn, so lines already waiting
 * are there from the first frame instead of arriving one frame later and
 * moving the page down (the test robot, 3c6e780e, 1 Nov 2026: on 3G New
 * analysis jumped 68 px as they came in).
 */
export function NoticeDock() {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    if (!node || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(DOCK_MEDIA);
    const place = () => setDock(media.matches ? node : null);
    place();
    media.addEventListener("change", place);
    return () => {
      media.removeEventListener("change", place);
      if (dock === node) setDock(null);
    };
  }, [node]);
  return <div ref={setNode} className={styles.dock} data-notice-dock="" />;
}

// ----- a page's own corner card --------------------------------------------------------------

let ownHost: HTMLElement | null = null;
const ownHostListeners = new Set<() => void>();
function setOwnHost(node: HTMLElement | null) {
  if (ownHost === node) return;
  ownHost = node;
  ownHostListeners.forEach((listener) => listener());
}
function subscribeOwnHost(listener: () => void) {
  ownHostListeners.add(listener);
  return () => {
    ownHostListeners.delete(listener);
  };
}
const noOwnHost = () => null;

/**
 * A page's own card in the corner stack, with the cards notify() raises, for a
 * card with more than one action (New analysis's "That didn't go through").
 * The first-call guide rises above the stack, the page keeps room for it and
 * it sits above Report a problem, so they all keep clear of this card too
 * (the test robot, a5ceb915, 60244251 and 7ead7db2, 1 Nov 2026: the card
 * floated on its own, under the guide's Skip guide and Next and over Report a
 * problem). Without a notice centre (a test) it stays where it is.
 */
export function InCorner({ children }: { children: ReactNode }) {
  const node = useSyncExternalStore(subscribeOwnHost, () => ownHost, noOwnHost);
  return node ? createPortal(children, node) : children;
}

const ICON = {
  error: AlertCircle,
  info: Info,
  success: CheckCircle2,
  work: BellRing,
  due: BellRing,
  lead: PhoneIncoming,
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
  docked = false,
}: {
  notice: Notice;
  /** How the card goes away; by default it leaves the notice list. */
  leave?: () => void;
  /** In the page's dock: one line with its action, in the page's flow. */
  docked?: boolean;
}) {
  const reporter = useReporterAvailable();
  const report = notice.tone === "error" && !notice.noReport && reporter;
  const [copied, setCopied] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [dismissFailed, setDismissFailed] = useState(false);
  const card = useRef<HTMLDivElement>(null);
  const opened = useRef(false);
  const key = seenKey(notice);
  const overBar = useSyncExternalStore(subscribeOverBar, isOverBar, notOverBar);
  const arrivesFolded = () =>
    docked ||
    overBar ||
    notice.folded === true ||
    notice.slim === true ||
    wasSeen(key);
  // Already on screen elsewhere (a sheet that closed): as it was, no arrival.
  const [again] = useState(() => placed.has(key));
  const [folded, setFolded] = useState(
    () => placed.get(key) ?? arrivesFolded(),
  );
  const [cardKey, setCardKey] = useState(key);
  if (cardKey !== key) {
    setCardKey(key);
    setFolded(arrivesFolded());
  }
  // Over a bar (a sheet's Save, a tab bar grown with large text) a card folds
  // to its pill at once. One opened from its pill stays open, above the bar,
  // until it folds again.
  const [held, setHeld] = useState(false);
  if (folded && held) setHeld(false);
  const [wasOver, setWasOver] = useState(overBar);
  if (wasOver !== overBar) {
    setWasOver(overBar);
    if (overBar && !docked && !held) setFolded(true);
  }
  useEffect(() => {
    placed.set(key, folded);
  }, [key, folded]);
  const Icon = ICON[notice.tone];
  const remove = useCallback(() => {
    placed.delete(key);
    if (leave) leave();
    else dismissNotice(notice.id);
  }, [key, leave, notice.id]);
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
    // A line in the page's dock stays until it is used or closed: one that
    // went by itself lifted the whole page by its height (QA robot a4e9034c,
    // 1 Nov 2026: a layout shift of 0.1 on every Leads load at 390 px). In the
    // corner or a sheet the same line goes by itself like every card ("Yes,
    // let it fade", the owner on "<name> is your lead now", 8 Nov 2026); the
    // bell keeps it.
    if (!timeout || notice.onDismiss || docked) return;
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
  }, [notice, remove, docked]);
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
      <div
        ref={card}
        className={styles.pill}
        data-tone={notice.tone}
        data-docked={docked || undefined}
        data-again={again || undefined}
      >
        <button
          type="button"
          className={styles.pillOpen}
          aria-expanded="false"
          onClick={() => {
            opened.current = true;
            setHeld(true);
            setFolded(false);
          }}
        >
          <Icon className={styles.icon} size={16} aria-hidden="true" />
          <span className={styles.pillText}>{notice.title}</span>
        </button>
        {/* A short-lived card's action stays too: its Undo is the point of
            it (ph2-36: Undo vanished once the card folded). */}
        {notice.action &&
        (notice.pillAction || docked || Boolean(notice.timeout)) ? (
          <CardAction
            action={notice.action}
            onRun={() => {
              if (!notice.onDismiss) remove();
            }}
          />
        ) : null}
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
      data-again={again || undefined}
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

// Whether the corner stack sits over a bar (NoticeCenter places it): its
// cards fold to pills there.
let overBar = false;
const barListeners = new Set<() => void>();
function setOverBar(next: boolean) {
  if (overBar === next) return;
  overBar = next;
  barListeners.forEach((listener) => listener());
}
function subscribeOverBar(listener: () => void) {
  barListeners.add(listener);
  return () => {
    barListeners.delete(listener);
  };
}
const isOverBar = () => overBar;
const notOverBar = () => false;

/** Cards that can wait while a lead's after-call question is open: news,
 *  never a problem, a due follow-up or a work alert. */
const WAITS_FOR_ANSWER = new Set<NoticeTone>(["info", "lead", "success"]);

/**
 * A lead's "How did it go?" is open (data-after-call): the corner's news waits
 * until it is answered, as it waits under a sheet, and comes after it with its
 * full time (Home studio, 13 Nov 2026: "… is your lead now", lifted over Save &
 * Close, covered "Pick a time instead").
 */
function watchAsking(changed: () => void) {
  const watch = new MutationObserver(changed);
  watch.observe(document.body, {
    attributes: true,
    attributeFilter: ["data-after-call"],
    childList: true,
    subtree: true,
  });
  return () => watch.disconnect();
}
const askingNow = () => document.querySelector("[data-after-call]") !== null;
const notAsking = () => false;

/** The room kept between the corner stack and a bar under it. */
const BAR_GAP = 8;

/** The room between two cards in the stack. */
const CARD_GAP = 10;

/**
 * Each of the stack's cards keeps one place in the page's layout, the stack's
 * base line, and is lifted into its row by `translate`, the newest highest. A
 * card arriving, leaving, folding to a pill or growing then moves no other
 * card's layout box, so the stack makes no layout shift (QA robot 69792ae8,
 * Home at 363: 0.12 as "Couldn't load" came and went; the Home studio's
 * diagnosis, 8 Nov 2026). A card's first lift isn't animated; later ones
 * glide (notice-center.module.css, [data-placed]).
 */
function placeCards(stack: HTMLElement) {
  const items = Array.from(stack.children) as HTMLElement[];
  let rise = 0;
  for (let at = items.length - 1; at >= 0; at -= 1) {
    const item = items[at];
    const height = item.offsetHeight;
    if (height < 1) continue;
    item.style.setProperty("translate", `0 ${-(rise + height)}px`);
    if (!item.hasAttribute("data-placed"))
      requestAnimationFrame(() => item.setAttribute("data-placed", ""));
    rise += height + CARD_GAP;
  }
}

type Seen = Pick<DOMRect, "top" | "bottom" | "left" | "right" | "height">;

/**
 * The stack as it is seen: its own box, which holds still at its base line,
 * and its cards above it (placeCards).
 */
function stackBox(stack: HTMLElement): Seen {
  let { top, bottom, left, right } = stack.getBoundingClientRect();
  for (const item of Array.from(stack.children)) {
    const box = item.getBoundingClientRect();
    if (box.height < 1) continue;
    top = Math.min(top, box.top);
    bottom = Math.max(bottom, box.bottom);
    left = Math.min(left, box.left);
    right = Math.max(right, box.right);
  }
  return { top, bottom, left, right, height: bottom - top };
}

/** Has `observer` watch the stack and each card in it: a card that comes is
 *  added (it is reported once), one that left is dropped. */
function watchCards(
  observer: ResizeObserver,
  stack: HTMLElement,
  seen: Set<Element>,
) {
  const now = new Set<Element>([stack, ...Array.from(stack.children)]);
  for (const item of seen)
    if (!now.has(item)) {
      observer.unobserve(item);
      seen.delete(item);
    }
  for (const item of now)
    if (!seen.has(item)) {
      observer.observe(item);
      seen.add(item);
    }
}

/**
 * How high the corner stack must sit, from the window's bottom, so that no bar
 * is under it; 0 where it stands (it is measured there, unlifted). A bar is
 * the sheet's footer or a short bar held at the bottom, fixed or sticky with a
 * bottom: the tab bar, the lead's Save & Close row, a page's action bar.
 * Content that scrolls is not one: the page and the sheet keep room for the
 * stack, so it scrolls clear.
 */
function liftOverBars(stack: HTMLElement, scope: HTMLElement): number {
  if (typeof document.elementsFromPoint !== "function") return 0;
  const home = stackBox(stack);
  if (home.height < 1) return 0;
  const view = window.innerHeight;
  const seen = new Map<Element, HTMLElement | null>();
  // The bar the topmost thing at a point belongs to, if any.
  const barAt = (node: Element | undefined): HTMLElement | null => {
    if (!node || !scope.contains(node)) return null;
    const path: Element[] = [];
    let bar: HTMLElement | null = null;
    for (let at: Element | null = node; at && at !== scope; ) {
      const known = seen.get(at);
      if (known !== undefined) {
        bar = known;
        break;
      }
      path.push(at);
      // The first-call guide rises above the stack by design, never under
      // it, so it is no bar (Seller Home, robot 8c687b6a, 3 Nov 2026: at
      // 1440 the two lifted over each other in turn, 0.108 of a 0.13 shift).
      if (at.hasAttribute("data-guide-card")) break;
      if (at instanceof HTMLElement) {
        const style = getComputedStyle(at);
        const held =
          (style.position === "fixed" || style.position === "sticky") &&
          (style.bottom || "auto") !== "auto";
        if (
          at.hasAttribute("data-sheet-footer") ||
          (held && at.getBoundingClientRect().height <= view * 0.4)
        ) {
          bar = at;
          break;
        }
      }
      at = at.parentElement;
    }
    for (const at of path) seen.set(at, bar);
    return bar;
  };
  let bottom = home.bottom;
  let lift = 0;
  // A bar above a bar (a Save row over a footer): a few rounds, never past
  // the top tenth of the window.
  for (
    let round = 0;
    round < 4 && bottom - home.height > view * 0.1;
    round += 1
  ) {
    let top = Infinity;
    for (let y = bottom - 4; y > bottom - home.height; y -= 16)
      for (const x of [
        home.left + 10,
        (home.left + home.right) / 2,
        home.right - 10,
      ]) {
        const hit = document
          .elementsFromPoint(x, y)
          .find((node) => !stack.contains(node));
        const bar = barAt(hit);
        if (bar) top = Math.min(top, bar.getBoundingClientRect().top);
      }
    if (top >= bottom) break;
    lift = Math.ceil(view - top + BAR_GAP);
    bottom = view - lift;
  }
  return lift;
}

/** The page's room for the stack (--sx-corner-h): its top to the window's bottom. */
function keepCornerRoom(node: HTMLElement) {
  const box = stackBox(node);
  setCornerRoom(box.height < 1 ? 0 : Math.ceil(window.innerHeight - box.top));
}

/** Less room keeps what's on screen in place (end-hold.ts). */
function setCornerRoom(room: number) {
  const root = document.documentElement;
  const was = parseFloat(root.style.getPropertyValue("--sx-corner-h")) || 0;
  const set = () => {
    if (room > 0) root.style.setProperty("--sx-corner-h", `${room}px`);
    else root.style.removeProperty("--sx-corner-h");
  };
  if (room < was) keepEndInView(set);
  else set();
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
  const asking = useSyncExternalStore(watchAsking, askingNow, notAsking);
  const [expanded, setExpanded] = useState(false);
  const [stack, setStack] = useState<HTMLDivElement | null>(null);
  // The stack's place for a page's own card (InCorner).
  const [own, setOwn] = useState<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    setOwnHost(own);
    return () => {
      if (ownHost === own) setOwnHost(null);
    };
  }, [own]);
  // How high the stack sits over a bar, for its glide down from a sheet.
  const lifted = useRef(0);
  const sheet = useTopModal();
  const pageDock = useSyncExternalStore(subscribeDock, () => dock, noDock);
  // A sheet on top takes every card; otherwise a phone page's dock takes the
  // new enquiries and work alerts, and the corner keeps the rest.
  const docking = sheet ? null : pageDock;
  const work = useNormalAlert();
  const workCard = useMemo(() => (work ? fromAlert(work) : null), [work]);
  const workGone = useCallback(() => {
    if (work) clearAlert(work.id);
  }, [work]);
  // A card that left the list is gone for good: it arrives anew next time.
  useEffect(() => {
    const live = new Set(
      [...list, ...(workCard ? [workCard] : [])].map(seenKey),
    );
    for (const key of placed.keys()) if (!live.has(key)) placed.delete(key);
    const ids = new Set(
      [...list, ...(workCard ? [workCard] : [])].map((item) => item.id),
    );
    for (const id of inDockHere.keys()) if (!ids.has(id)) inDockHere.delete(id);
  }, [list, workCard]);

  // The page keeps room for the stack, so content scrolls clear of it: the
  // band from the stack's top to the window's bottom, which the shell adds to
  // the end of the page (shell/lightbox-shell.module.css). No card, no room.
  // Each card is lifted into its row before it is drawn (placeCards), after
  // every change here and whenever a card's own size changes (a fold, a page's
  // own card).
  const cardSizes = useRef<{
    observer: ResizeObserver;
    seen: Set<Element>;
  } | null>(null);
  useEffect(() => {
    const node = stack;
    if (!node || typeof ResizeObserver === "undefined") return;
    const publish = () => keepCornerRoom(node);
    publish();
    const observer = new ResizeObserver(() => {
      placeCards(node);
      publish();
    });
    const seen = new Set<Element>();
    cardSizes.current = { observer, seen };
    watchCards(observer, node, seen);
    window.addEventListener("resize", publish);
    return () => {
      observer.disconnect();
      cardSizes.current = null;
      window.removeEventListener("resize", publish);
      setCornerRoom(0);
    };
  }, [stack]);
  useLayoutEffect(() => {
    if (!stack) return;
    placeCards(stack);
    keepCornerRoom(stack);
    const sizes = cardSizes.current;
    if (sizes) watchCards(sizes.observer, stack, sizes.seen);
  });

  // Inside a sheet the stack is a popover on its top layer (as the picker is),
  // so its cards show and answer taps, and the sheet's words keep room to
  // scroll clear of it (kit sheet: data-sheet-body, --sx-sheet-room, space
  // after the words that leaves a held Save row at the bottom). In a sheet or
  // on a page it sits above any bar under its corner, by the bar's measured
  // top: the sheet's footer, the lead's Save & Close row, a tab bar grown with
  // large text. Over a bar its cards fold to pills (orchestrator, 3 Nov 2026:
  // "… is your lead now" covered the lead sheet's Save bar).
  useEffect(() => {
    // A stack on its way out (its sheet closed) is left alone.
    if (!stack?.isConnected) return;
    const scope = sheet ?? document.body;
    if (sheet)
      try {
        if (!stack.matches(":popover-open")) stack.showPopover();
      } catch {
        // Without popovers it still sits inside the sheet, over its panel.
      }
    const across = (a: Seen, b: Seen) => a.left < b.right && b.left < a.right;
    let body: HTMLElement | null = null;
    let frame = 0;
    let watch = () => {};
    const place = () => {
      frame = 0;
      watch();
      // Gliding down from a sheet that closed: it is placed once it lands.
      if (stack.hasAttribute("data-glide")) return;
      const before = lifted.current;
      stack.style.removeProperty("--sx-stack-lift");
      const lift = stack.textContent ? liftOverBars(stack, scope) : 0;
      if (lift > 0) stack.style.setProperty("--sx-stack-lift", `${lift}px`);
      lifted.current = lift;
      setOverBar(lift > 0);
      if (lift !== before) keepCornerRoom(stack);
      if (!sheet) return;
      body?.style.removeProperty("--sx-sheet-room");
      body = sheet.querySelector<HTMLElement>("[data-sheet-body]");
      if (!body) return;
      const box = stackBox(stack);
      const words = body.getBoundingClientRect();
      const room =
        box.height > 0 && across(box, words)
          ? Math.ceil(words.bottom - box.top + 12)
          : 0;
      if (room > 0) body.style.setProperty("--sx-sheet-room", `${room}px`);
    };
    // Out of a sheet that closed (the after-call sheet, with its Undo card),
    // the stack glides down from where it sat over the sheet's bar instead of
    // jumping (phone personas ph2-36, 1 Nov 2026: about 160 px within 2 s).
    const from = sheet ? 0 : lifted.current;
    let glide = 0;
    let landed = 0;
    if (from) {
      lifted.current = 0;
      stack.style.setProperty("--sx-stack-lift", `${from}px`);
      stack.setAttribute("data-glide", "");
      glide = requestAnimationFrame(() => {
        glide = requestAnimationFrame(() =>
          stack.style.removeProperty("--sx-stack-lift"),
        );
      });
      landed = window.setTimeout(() => {
        stack.removeAttribute("data-glide");
        place();
      }, 600);
    } else place();
    // A bar that comes or goes (Log a call opens its Save row) or scrolls
    // away with the words: next frame.
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(place);
    };
    const scrolled = { capture: true, passive: true } as const;
    window.addEventListener("scroll", schedule, scrolled);
    // A screen that slid in: its fixed bars (Leads' Call band) reach their
    // place only as the motion ends, which moves no element, so measure again.
    window.addEventListener(SCREEN_SETTLED_EVENT, schedule);
    // The stack's own box holds still (placeCards): its cards' sizes move it.
    const sized =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    const watched = new Set<Element>();
    watch = () => {
      if (sized) watchCards(sized, stack, watched);
    };
    watch();
    const changed = new MutationObserver(schedule);
    changed.observe(scope, { childList: true, subtree: true });
    window.addEventListener("resize", place);
    return () => {
      sized?.disconnect();
      changed.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", schedule, scrolled);
      window.removeEventListener(SCREEN_SETTLED_EVENT, schedule);
      cancelAnimationFrame(frame);
      cancelAnimationFrame(glide);
      window.clearTimeout(landed);
      body?.style.removeProperty("--sx-sheet-room");
      stack.style.removeProperty("--sx-stack-lift");
      setOverBar(false);
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

  const docks = (item: Notice) =>
    item.dock === true || DOCKED_TONES.has(item.tone);
  placeLines(
    pageDock,
    [...list.filter(docks), ...(workCard ? [workCard] : [])].map(
      (item) => item.id,
    ),
    sheet !== null,
  );
  const inDock = (item: Notice) => inDockHere.get(item.id) === true;
  const docked = docking
    ? list.filter((item) => docks(item) && inDock(item))
    : [];
  const corner = (
    docking ? list.filter((item) => !docks(item) || !inDock(item)) : list
  ).filter((item) => !asking || !WAITS_FOR_ANSWER.has(item.tone));
  const workDocked = !!docking && !!workCard && inDock(workCard);
  const cornerWork = workDocked ? null : workCard;
  const dockWork = workDocked ? workCard : null;
  const waiting = Math.max(0, corner.length - SHOWN);
  // Once no card waits, the next pile starts folded again.
  if (expanded && waiting === 0) setExpanded(false);
  // The newest first: a card arrives at the top of the stack, so the cards
  // already there never move (orchestrator, 1 Nov 2026: a card joining below
  // lifted the others, a layout shift); older ones wait under "+N more".
  const shownList = [...(expanded ? corner : corner.slice(-SHOWN))].reverse();
  const dockList = [...docked.slice(-SHOWN)].reverse();
  // In an open sheet, one card: the newest, else the work alert. A pile there
  // covered the sheet's own controls (orchestrator, 8 Nov 2026: three cards over
  // the lead sheet's actions at 363); the rest come back with the page's stack
  // once the sheet closes.
  const sheetCard = sheet && corner.length ? corner[corner.length - 1] : null;
  // While a sheet holds the dock's lines (above), the dock keeps their room on
  // the page under it, so the page doesn't rise as a lead's sheet opens and
  // drop as it closes (QA robot 95abddab and 77641e07, 3 Nov 2026: 52 px each
  // way). Measured while the lines are in the dock.
  const dockRoom = useRef(0);
  const dockLines = docking ? dockList.length + (dockWork ? 1 : 0) : -1;
  useLayoutEffect(() => {
    if (!docking) return;
    const lines = docking.firstElementChild;
    if (!lines) {
      dockRoom.current = 0;
      return;
    }
    const style = getComputedStyle(lines);
    dockRoom.current =
      lines.getBoundingClientRect().height +
      (parseFloat(style.marginTop) || 0) +
      (parseFloat(style.marginBottom) || 0);
  }, [docking, dockLines]);
  useLayoutEffect(() => {
    if (!pageDock) return;
    const hold = sheet !== null && dockRoom.current > 0;
    pageDock.toggleAttribute("data-held", hold);
    if (hold)
      pageDock.style.setProperty(
        "--sx-dock-held",
        `${Math.round(dockRoom.current)}px`,
      );
    else pageDock.style.removeProperty("--sx-dock-held");
  }, [sheet, pageDock]);

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
          {cornerWork && !sheetCard ? (
            <NoticeCard
              key={cornerWork.id}
              notice={cornerWork}
              leave={workGone}
            />
          ) : null}
          {(sheet ? (sheetCard ? [sheetCard] : []) : shownList).map(
            (notice) => (
              <NoticeCard key={notice.id} notice={notice} />
            ),
          )}
          {waiting > 0 && !sheet ? (
            <button
              type="button"
              className={styles.more}
              aria-expanded={expanded}
              onClick={() => setExpanded((now) => !now)}
            >
              {expanded ? "Show fewer" : `+${waiting} more`}
            </button>
          ) : null}
          {/* A page's own card (InCorner), nearest the corner. */}
          <div ref={setOwn} className={styles.own} data-corner-own="" />
        </div>
      </StackHost>
      {/* On a phone page with a dock: one line each, in the page's flow. */}
      {docking && (dockWork || dockList.length)
        ? createPortal(
            <div
              className={styles.docked}
              aria-live="polite"
              data-capture-skip=""
            >
              {dockWork ? (
                <NoticeCard
                  key={dockWork.id}
                  notice={dockWork}
                  leave={workGone}
                  docked
                />
              ) : null}
              {dockList.map((notice) => (
                <NoticeCard key={notice.id} notice={notice} docked />
              ))}
            </div>,
            docking,
          )
        : null}
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
