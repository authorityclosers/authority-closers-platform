"use client";

/**
 * Home's metric pages (owner, 31 Oct 2026: "a metric slider"): on a phone the
 * cards are page one and a swipe brings the next, its figures rising in.
 * Native scroll-snap carries the momentum; the dots show where you are and
 * move you. Every page is the same 2x2 shape, so the slider is exactly as
 * tall as its cards. From 1024 px every page shows at once, one row each,
 * titled. No motion when the person asks for less.
 */

import {
  ArrowRight,
  CalendarCheck,
  ChevronRight,
  ClipboardList,
  Clock,
  Info,
  PhoneCall,
  PhoneMissed,
  PhoneOutgoing,
  Rocket,
  Target,
  Timer,
  Users,
  UserX,
} from "lucide-react";
import Link from "next/link";
import {
  type CSSProperties,
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { Sheet } from "../ui/sheet";
import { breakLength } from "./home-today";
import styles from "./metric-pager.module.css";

/** A page: its label (the slide's name), its short tab name, and its cards. */
export type Page = {
  key: string;
  label: string;
  tab?: string;
  content: ReactNode;
};

/** Material's elastic tab indicator, sampled at 0, 25, 50, 75 and 100 % of a page
 *  step (motion-research-2.md): where its left edge is and how wide it is, in
 *  tabs. Linear between samples. */
const INK_LEFT = [0, 0.076, 0.293, 0.617, 1];
const INK_WIDTH = [1, 1.307, 1.414, 1.307, 1];

/** One page's step along the track: its width and the seam after it. */
function stepOf(node: HTMLElement): number {
  const first = node.children[0] as HTMLElement | undefined;
  const second = node.children[1] as HTMLElement | undefined;
  const step = first && second ? second.offsetLeft - first.offsetLeft : 0;
  return step > 0 ? step : node.clientWidth || 1;
}

function inkAt(at: number, still: boolean): [number, number] {
  const step = Math.floor(at);
  const part = at - step;
  if (still || part === 0) return [at, 1];
  const slot = Math.min(3, Math.floor(part * 4));
  const t = part * 4 - slot;
  const left = INK_LEFT[slot] + (INK_LEFT[slot + 1] - INK_LEFT[slot]) * t;
  const width = INK_WIDTH[slot] + (INK_WIDTH[slot + 1] - INK_WIDTH[slot]) * t;
  return [step + left, width];
}

export function MetricPager({
  pages,
  label,
}: {
  pages: Page[];
  label: string;
}) {
  const track = useRef<HTMLDivElement>(null);
  const shell = useRef<HTMLElement>(null);
  const [page, setPage] = useState(0);
  useEffect(() => {
    const node = track.current;
    if (!node) return;
    // Once a frame: the swipe's position moves the tabs' bar with the finger,
    // stretching mid-swipe (owner, 15 Nov 2026; motion-research-2.md). No
    // vibration on settle.
    const still =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        const at = node.scrollLeft / stepOf(node);
        const [inkX, inkWidth] = inkAt(at, still);
        shell.current?.style.setProperty("--pager-at", String(at));
        shell.current?.style.setProperty("--pager-ink-x", String(inkX));
        shell.current?.style.setProperty("--pager-ink", String(inkWidth));
        const index = Math.max(0, Math.min(pages.length - 1, Math.round(at)));
        setPage(index);
      });
    };
    node.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      node.removeEventListener("scroll", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [pages.length]);
  const go = (index: number) => {
    const node = track.current;
    if (!node) return;
    setPage(index);
    const reduce = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    node.scrollTo({
      left: index * stepOf(node),
      behavior: reduce ? "auto" : "smooth",
    });
  };
  return (
    <section
      ref={shell}
      className={styles.pager}
      aria-roledescription="carousel"
      aria-label={label}
    >
      {pages.length > 1 ? (
        <div
          className={styles.tabs}
          role="tablist"
          aria-label={`${label}, pages`}
        >
          {pages.map((item, index) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={index === page}
              aria-label={`${item.tab ?? item.label}, ${index + 1} of ${pages.length}`}
              className={styles.tab}
              onClick={() => go(index)}
            >
              <span>{item.tab ?? item.label}</span>
              <i aria-hidden="true" />
            </button>
          ))}
          {/* One bar for the chosen page, sliding with the swipe. */}
          <span
            className={styles.tabBar}
            aria-hidden="true"
            style={{ "--pages": pages.length } as CSSProperties}
          />
        </div>
      ) : null}
      <div ref={track} className={styles.track}>
        {pages.map((item, index) => (
          <div
            key={item.key}
            className={styles.page}
            aria-roledescription="slide"
            aria-label={`${index + 1} of ${pages.length}: ${item.label}`}
            data-active={index === page || undefined}
          >
            {pages.length > 1 ? (
              <h3 className={styles.pageTitle}>{item.label}</h3>
            ) : null}
            {item.content}
          </div>
        ))}
      </div>
    </section>
  );
}

/** One figure: a big number and what it is. */
export type More = {
  label: string;
  value: string | null;
  /** A second line: the other side's figure. */
  note?: string;
  /** Needs someone: the number goes red, with a small dot. */
  red?: boolean;
  /** The exact list behind the number, one tap away. */
  href?: string;
  /** What the number means, on hover (computers). */
  help?: string;
  /** For tests and the screen's own links. */
  key?: string;
};

/** Each figure's look on the owner's Home (14 Nov 2026 design): its tone, its icon, what it means and its action. */
const LOOK: Record<
  string,
  { tone: string; Icon: typeof Rocket; meaning: string; action?: string }
> = {
  new: {
    tone: "emerald",
    Icon: Rocket,
    meaning: "Awaiting first call",
    action: "View waiting leads",
  },
  open: {
    tone: "violet",
    Icon: ClipboardList,
    meaning: "Open now",
    action: "View open leads",
  },
  late: {
    tone: "orange",
    Icon: Clock,
    meaning: "Overdue now",
    action: "View overdue leads",
  },
  unowned: {
    tone: "rose",
    Icon: UserX,
    meaning: "Needs assignment",
    action: "Assign leads",
  },
  tried: {
    tone: "emerald",
    Icon: PhoneOutgoing,
    meaning: "Outgoing attempts",
    action: "View calls",
  },
  connected: {
    tone: "violet",
    Icon: PhoneCall,
    meaning: "Answered calls",
    action: "View connected",
  },
  not_connected: {
    tone: "orange",
    Icon: PhoneMissed,
    meaning: "Unanswered calls",
    action: "View not connected",
  },
  talk: {
    tone: "rose",
    Icon: Timer,
    meaning: "Measured call time",
    action: "View call duration",
  },
  // Its note says what it counts ("11 connected · 21 not"), so no meaning of its own.
  known: {
    tone: "violet",
    Icon: PhoneCall,
    meaning: "",
    action: "View calls",
  },
  first_call: { tone: "emerald", Icon: Timer, meaning: "Median response time" },
  coverage: {
    tone: "emerald",
    Icon: Target,
    meaning: "Leads called at least once",
  },
  interested: {
    tone: "violet",
    Icon: ArrowRight,
    meaning: "Of the leads called today",
  },
  reached: { tone: "orange", Icon: Users, meaning: "Unique leads spoken to" },
  meetings: {
    tone: "rose",
    Icon: CalendarCheck,
    meaning: "Meetings given today",
  },
};
const PLAIN = { tone: "emerald", Icon: Target, meaning: "", action: "" };

/** A figure's value: a plain number or percent counts up; a duration keeps its unit letters smaller beside the
 *  digits ("42 h 18 m"), so the number stays the thing you read. */
function Value({ value }: { value: string }) {
  if (/^\d+%?$/.test(value)) return <Count value={value} />;
  if (!/\d/.test(value)) return <span>{value}</span>;
  // Spaces kept as text, so "25 min" reads as two words, not "25min".
  const parts = value.match(/\d+|\s+|[^\d\s]+/g) ?? [value];
  return (
    <>
      {parts.map((part, index) =>
        /^\s+$/.test(part) ? (
          " "
        ) : /^\d+$/.test(part) ? (
          <span key={index}>{part}</span>
        ) : (
          <small key={index} className={styles.unit}>
            {part}
          </small>
        ),
      )}
    </>
  );
}

export function MoreFigures({ figures }: { figures: More[] }) {
  // A figure with no page of its own yet says how it's counted.
  const [explained, setExplained] = useState<More | null>(null);
  const told = explained
    ? (explained.key && LOOK[explained.key]) || PLAIN
    : null;
  return (
    <>
      <ul className={styles.more}>
        {figures.map((figure, index) => {
          const look = (figure.key && LOOK[figure.key]) || PLAIN;
          const meaning = figure.note
            ? look.meaning
              ? `${look.meaning} · ${figure.note}`
              : figure.note
            : look.meaning || figure.help || "";
          const body = (
            <>
              <span className={styles.figHead}>
                <span className={styles.figIcon} aria-hidden="true">
                  <look.Icon />
                </span>
                <span className={styles.figureLabel}>
                  <span>{figure.label}</span>
                </span>
                {figure.href ? (
                  <ChevronRight
                    className={styles.figChevron}
                    aria-hidden="true"
                  />
                ) : null}
              </span>
              {/* The number and what it means side by side (owner, 15 Nov
                2026: the right half was empty). */}
              <span className={styles.figValue}>
                <strong aria-busy={figure.value === null || undefined}>
                  {figure.value === null ? " " : <Value value={figure.value} />}
                </strong>
                {meaning ? (
                  <span className={styles.figureNote}>{meaning}</span>
                ) : null}
              </span>
              {figure.href && look.action ? (
                <span className={styles.figAction}>
                  {look.action}
                  <ChevronRight aria-hidden="true" />
                </span>
              ) : !figure.href && figure.help ? (
                <span className={styles.figAction}>
                  How it&apos;s counted
                  <Info aria-hidden="true" />
                </span>
              ) : null}
            </>
          );
          const props = {
            className: styles.figure,
            "data-red": figure.red || undefined,
            "data-figure": figure.key,
            "data-tone": look.tone,
            title: figure.help,
            style: { "--i": index } as CSSProperties,
          };
          return (
            <li key={figure.key ?? figure.label}>
              {figure.href ? (
                <Link href={figure.href} {...props}>
                  {body}
                </Link>
              ) : figure.help ? (
                <button
                  type="button"
                  {...props}
                  aria-haspopup="dialog"
                  onClick={() => setExplained(figure)}
                >
                  {body}
                </button>
              ) : (
                <div {...props}>{body}</div>
              )}
            </li>
          );
        })}
      </ul>
      <Sheet
        open={explained !== null}
        onClose={() => setExplained(null)}
        title={explained?.label ?? ""}
      >
        {explained && told ? (
          <div className={styles.explain} data-tone={told.tone}>
            <p className={styles.explainValue}>
              <strong>{explained.value ?? "–"}</strong>
              {told.meaning ? <span>{told.meaning}</span> : null}
            </p>
            <p className={styles.explainHow}>{explained.help}</p>
          </div>
        ) : null}
      </Sheet>
    </>
  );
}

/** When Home's first reveal began: the hero counts that mount with it climb from 0,
 *  once a session (a client-side visit back to Home doesn't count again). */
let revealedAt: number | null = null;

function inFirstReveal(): boolean {
  const now = performance.now();
  if (revealedAt === null) revealedAt = now;
  return now - revealedAt < 300;
}

/**
 * A number that moves only when the move means something (owner, 31 Oct 2026:
 * "numbers count up"; motion-research-2.md section 4). `reveal`: one of today's
 * hero counts, which climb from 0 on Home's first reveal of the session. A change
 * in the same `context` (a live update) counts from the number shown; a new
 * context (another side or day) fades the new number in and never counts. Under
 * 10, text that isn't a whole number (a percentage, a time), a hidden page and
 * reduced motion: the number shows at once. The span is written directly, so
 * React never holds a stale text node.
 */
export function Count({
  value,
  reveal = false,
  context,
}: {
  value: string;
  reveal?: boolean;
  context?: string;
}) {
  const node = useRef<HTMLSpanElement>(null);
  const last = useRef<{ value: string; context?: string } | null>(null);
  useLayoutEffect(() => {
    const element = node.current;
    if (!element) return;
    const before = last.current;
    last.current = { value, context };
    element.textContent = value;
    const quiet =
      // Tests read the figure, not the motion.
      process.env.NODE_ENV === "test" ||
      document.hidden ||
      typeof window.matchMedia !== "function" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (before && before.value === value) return;
    if (before && before.context !== context) {
      // Another side or day: the new number fades in; opacity, not motion.
      if (process.env.NODE_ENV !== "test")
        element.animate?.([{ opacity: 0.3 }, { opacity: 1 }], {
          duration: 150,
          easing: "ease-out",
        });
      return;
    }
    const target = /^\d+$/.test(value) ? Number(value) : null;
    const start = before
      ? /^\d+$/.test(before.value)
        ? Number(before.value)
        : null
      : reveal && inFirstReveal()
        ? 0
        : null;
    if (quiet || target === null || start === null || target < 10) return;
    const digits = String(target).length;
    const length = before ? (digits >= 3 ? 400 : 300) : digits >= 3 ? 600 : 400;
    const began = performance.now();
    let frame = 0;
    let done = false;
    const step = (now: number) => {
      element.textContent = String(
        countedTo(start, target, now - began, length, 4),
      );
      if (now - began < length) frame = requestAnimationFrame(step);
      else done = true;
    };
    element.textContent = String(start);
    frame = requestAnimationFrame(step);
    // Frames stop in a hidden page: the real number lands when the time is up.
    const finish = window.setTimeout(() => {
      if (done) return;
      cancelAnimationFrame(frame);
      element.textContent = value;
      done = true;
    }, length + 100);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(finish);
      element.textContent = value;
      // Cut short (a new value, or React's development double run): give back
      // where it started, so the next run counts from there.
      if (!done) last.current = before;
    };
  }, [value, context, reveal]);
  return <span ref={node} />;
}

/** The number a count-up shows `elapsed` ms into `length`, eased out. A frame's time can
 *  be from before the count began (a long first-load task), so the progress is held to
 *  0..1: never a minus number, never past the real one (QA 73c90cfa, 31 Oct 2026). */
export function countedTo(
  start: number,
  target: number,
  elapsed: number,
  length: number,
  /** The ease-out's strength: 3 cubic, 4 quart (90 % shown by 44 % of the time). */
  power = 3,
): number {
  const progress = Math.min(1, Math.max(0, elapsed / length));
  return Math.round(start + (target - start) * (1 - (1 - progress) ** power));
}

export const share = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : "–";

export const minutes = (seconds: number) =>
  breakLength(Math.round(seconds / 60));
