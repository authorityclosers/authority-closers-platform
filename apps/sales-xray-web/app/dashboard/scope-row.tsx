"use client";

/**
 * Home's scope row (owner's chosen Home, 01_Home.png, 14 Nov 2026): Team | Me
 * on the left, the day on the right. The date picks a day to look back on
 * (owner, 15 Nov 2026), and the day's figures follow it (home-day.ts). The
 * date is India's, drawn from the first paint, and turns over at midnight.
 */

import { CalendarDays, ChevronDown, X } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import { DaySheet } from "./day-sheet";
import { dayName, useHomeDay } from "./home-day";
import { ModeSwitch, type HomeMode } from "./mode-switch";
import styles from "./scope-row.module.css";

const DAY = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});
const FULL = new Intl.DateTimeFormat("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "Asia/Kolkata",
});
/** Today in India, as the top of Home counts it ("2026-11-15"). */
const IST_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

/** "Sat, 15 Nov": the year is said, not shown, so the row fits one line. */
export function todayLine(now: Date): string {
  const part = Object.fromEntries(
    DAY.formatToParts(now).map((piece) => [piece.type, piece.value]),
  );
  return `${part.weekday}, ${part.day} ${part.month}`;
}

function everyMinute(onChange: () => void) {
  const timer = window.setInterval(onChange, 60_000);
  return () => window.clearInterval(timer);
}

// India's day on the server and the phone alike, so the date is there from
// the first paint, the loading outline included (critique 01).
const nowDay = () => IST_DAY.format(new Date());

/** How far the Today row reaches under this one: Home's 12 px gap and its 44 px
 *  row. The bar turns compact once that row has gone under it. */
const TODAY_ROW = 56;
/** The dead band before it turns back, more than a finger's 8 px slop. */
const DEAD_BAND = 12;

export function ScopeRow({
  value,
  onChange,
}: {
  value: HomeMode;
  onChange: (next: HomeMode) => void;
}) {
  // The day, not the minute, so the row draws again only at midnight.
  const today = useSyncExternalStore(everyMinute, nowDay, nowDay);
  // A chosen past day (owner, 15 Nov 2026: the date picks a day to look back on).
  const [chosen, choose] = useHomeDay();
  const [picking, setPicking] = useState(false);
  const date = new Date(`${chosen ?? today}T12:00:00+05:30`);
  // Scrolled past: the bar shows this scope in the workspace name's place
  // (motion-research-2.md section 2), through the slot the bar keeps for it.
  const row = useRef<HTMLDivElement>(null);
  const mark = useRef<HTMLSpanElement>(null);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => {
    const sentinel = mark.current;
    const bar = document.querySelector<HTMLElement>("header[data-home]");
    if (!sentinel || !bar || typeof IntersectionObserver !== "function") return;
    setSlot(bar.querySelector<HTMLElement>("[data-home-scope-slot]"));
    const line = Math.round(bar.getBoundingClientRect().bottom) - TODAY_ROW;
    const compact = (on: boolean) => bar.toggleAttribute("data-compact", on);
    const past = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting && entry.boundingClientRect.top < line)
          compact(true);
      },
      { rootMargin: `${-line}px 0px 0px 0px` },
    );
    const back = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) compact(false);
      },
      { rootMargin: `${-(line + DEAD_BAND)}px 0px 0px 0px` },
    );
    past.observe(sentinel);
    back.observe(sentinel);
    return () => {
      past.disconnect();
      back.disconnect();
      compact(false);
    };
  }, []);
  const toTop = () => {
    const behavior =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth";
    row.current
      ?.closest<HTMLElement>(".studio-main")
      ?.scrollTo({ top: 0, behavior });
    window.scrollTo({ top: 0, behavior });
  };
  const scopeWord = value === "mine" ? "Me" : "Team";
  const dayWord = chosen ? dayName(chosen) : "Today";
  return (
    <div ref={row} className={styles.row} data-pull-still="">
      <ModeSwitch value={value} onChange={onChange} look="home" />
      <button
        type="button"
        className={styles.today}
        data-past={chosen ? "" : undefined}
        aria-haspopup="dialog"
        aria-label={`${chosen ? "Showing" : "Today,"} ${FULL.format(date)}. Pick a day`}
        onClick={() => setPicking(true)}
      >
        <CalendarDays size={18} strokeWidth={2} aria-hidden="true" />
        <span aria-hidden="true">{todayLine(date)}</span>
        <ChevronDown size={16} strokeWidth={2.25} aria-hidden="true" />
      </button>
      <DaySheet
        open={picking}
        onClose={() => setPicking(false)}
        day={chosen}
        onPick={choose}
      />
      <span ref={mark} className={styles.mark} aria-hidden="true" />
      {slot
        ? createPortal(
            <>
              <button
                type="button"
                className={styles.compact}
                onClick={toTop}
                aria-label={`${scopeWord}, ${dayWord}. Back to the top`}
              >
                <small>{scopeWord}</small>
                <b>{dayWord}</b>
              </button>
              {chosen ? (
                <button
                  type="button"
                  className={styles.compactClear}
                  onClick={() => choose(null)}
                  aria-label="Back to today"
                >
                  <X size={18} strokeWidth={2.25} aria-hidden="true" />
                </button>
              ) : null}
            </>,
            slot,
          )
        : null}
    </div>
  );
}
