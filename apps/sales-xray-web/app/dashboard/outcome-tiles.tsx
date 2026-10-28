"use client";

/**
 * How sales are going, as tiles (owner Home v3, 28 Oct 2026: "B's tiles"; the
 * owner's #54 asked for cards and widgets, every pixel used). Won and
 * Interested carry the period's days as small bars; New leads its first-call
 * time; Connected a share ring. Every tile opens its detail: the days in full,
 * who did it, and the leads behind it. The numbers mean what they meant in the
 * list before (leads-client Outcomes); nothing is estimated.
 */

import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronRight,
  Minus,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import type {
  DayOutcome,
  Outcomes,
  Performance,
  Period,
  SellerOutcome,
} from "../leads/leads-client";
import { Avatar, Segmented } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import { OutcomesSkeleton } from "./sales-home-skeleton";
import styles from "./outcome-tiles.module.css";

export const PERIODS: { key: "1" | "7" | "30"; label: string }[] = [
  { key: "1", label: "Today" },
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
];

const percent = (part: number, whole: number) =>
  whole ? `${Math.round((part / whole) * 100)}%` : "–";

export function minutesWords(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 6) / 10;
  return hours < 24 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}

/** "the previous 7 days", or "yesterday" for today. */
export const beforeWords = (period: Period) =>
  period === 1 ? "yesterday" : `the previous ${period} days`;

const reduced = () =>
  typeof window.matchMedia !== "function" ||
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Counts from the last number shown to the real one; instant under reduced motion. */
function useCountUp(value: number): number {
  // Drawn once data is in, in the browser: it starts from 0 unless motion is reduced.
  const [shown, setShown] = useState(() =>
    typeof window === "undefined" || reduced() ? value : 0,
  );
  const from = useRef(shown);
  useEffect(() => {
    let frame = 0;
    const start = from.current;
    if (reduced() || start === value) {
      frame = requestAnimationFrame(() => setShown(value));
      from.current = value;
      return () => cancelAnimationFrame(frame);
    }
    const began = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - began) / 600);
      const next = Math.round(
        start + (value - start) * (1 - (1 - progress) ** 3),
      );
      setShown(next);
      from.current = next;
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return shown;
}

function Count({ value }: { value: number }) {
  return <>{useCountUp(value)}</>;
}

/** The change against the period before, in counts: "2 more", "1 fewer". */
export function changeWords(value: number, previous: number): string {
  const diff = value - previous;
  if (diff === 0) return "Same as before";
  return diff > 0 ? `${diff} more` : `${-diff} fewer`;
}

function Change({ value, previous }: { value: number; previous: number }) {
  const diff = value - previous;
  const Icon = diff > 0 ? ArrowUpRight : diff < 0 ? ArrowDownRight : Minus;
  return (
    <span
      className={styles.change}
      data-trend={diff > 0 ? "up" : diff < 0 ? "down" : "flat"}
    >
      <Icon size={13} aria-hidden="true" />
      {changeWords(value, previous)}
    </span>
  );
}

const dayLabel = (iso: string, long = false) =>
  new Date(`${iso}T12:00:00+05:30`).toLocaleDateString("en-IN", {
    weekday: "short",
    ...(long ? { day: "numeric", month: "short" } : {}),
    timeZone: "Asia/Kolkata",
  });

/**
 * The period's days, oldest first. Seven bars for a week (a phone shows seven
 * at most); a line for 30 days; nothing for one day.
 */
function DayChart({
  days,
  pick,
  label,
  large = false,
}: {
  days: readonly DayOutcome[];
  pick: (day: DayOutcome) => number;
  label: string;
  large?: boolean;
}) {
  if (days.length < 2) return null;
  const values = days.map(pick);
  const most = Math.max(1, ...values);
  const summary = `${label} by day: ${days.map((day, index) => `${dayLabel(day.day, true)} ${values[index]}`).join(", ")}`;
  if (days.length <= 7)
    return (
      <span className={styles.chart} data-large={large || undefined}>
        <span className={styles.bars} role="img" aria-label={summary}>
          {values.map((value, index) => (
            <span key={days[index].day} className={styles.barSlot}>
              {/* Each day's number on its bar (skill rule 13: label the values). */}
              <small>{value}</small>
              <span
                className={styles.bar}
                data-zero={value === 0 || undefined}
                style={{
                  height: value ? `${(value / most) * 100}%` : undefined,
                }}
              />
            </span>
          ))}
        </span>
        <span className={styles.axis} aria-hidden="true">
          {large ? (
            days.map((day) => <span key={day.day}>{dayLabel(day.day)}</span>)
          ) : (
            <>
              <span>{dayLabel(days[0].day)}</span>
              <span>{dayLabel(days[days.length - 1].day)}</span>
            </>
          )}
        </span>
      </span>
    );
  const width = 100;
  const height = 32;
  const points = values
    .map(
      (value, index) =>
        `${((index / (values.length - 1)) * width).toFixed(2)},${(height - (value / most) * (height - 2) - 1).toFixed(2)}`,
    )
    .join(" ");
  return (
    <span className={styles.chart} data-large={large || undefined}>
      <svg
        className={styles.line}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={summary}
      >
        <polyline points={points} vectorEffect="non-scaling-stroke" />
      </svg>
      <span className={styles.axis} aria-hidden="true">
        <span>{dayLabel(days[0].day, true)}</span>
        <span>{dayLabel(days[days.length - 1].day, true)}</span>
      </span>
    </span>
  );
}

function Ring({ part, whole }: { part: number; whole: number }) {
  const share = whole ? part / whole : 0;
  const around = 2 * Math.PI * 22;
  return (
    <span className={styles.ring} aria-hidden="true">
      <svg viewBox="0 0 52 52">
        <circle className={styles.ringTrack} cx="26" cy="26" r="22" />
        <circle
          className={styles.ringFill}
          cx="26"
          cy="26"
          r="22"
          strokeDasharray={`${(share * around).toFixed(2)} ${around.toFixed(2)}`}
        />
      </svg>
    </span>
  );
}

/** What a tile reads: the period's report. */
export type TileData = {
  now: Outcomes;
  before: Outcomes;
  days: readonly DayOutcome[];
  sellers: readonly SellerOutcome[];
  /** Open leads by stage, right now. */
  pipeline: Record<string, number>;
  period: Period;
};

/**
 * One tile, as configuration (orchestrator, 28 Oct 2026: the set must switch
 * between the owner's outcomes and an operations-first set without layout
 * work). A tile without `compare` is a right-now count, not the period's.
 */
export type TileSpec = {
  label: string;
  tone: "good" | "violet" | "teal" | "slate" | "warn";
  /** The figure. */
  shown: (data: TileData) => ReactNode;
  /** The same figure for the period before, for the change. */
  compare?: (outcomes: Outcomes) => number;
  note: (data: TileData) => string;
  /** The days as small bars on the tile (the detail draws them whenever `day` is set). */
  bars?: boolean;
  /** A share ring beside the figure: [part, whole]. */
  ring?: (data: TileData) => [number, number];
  day?: (day: DayOutcome) => number;
  /** Who did it, for the detail, highest first. */
  seller?: (seller: SellerOutcome) => number;
  sellerWords?: (seller: SellerOutcome) => string;
  link: { href: string; label: string };
  explain: string;
};

const count = (value: number) => <Count value={value} />;

export const TILES = {
  won: {
    label: "Won",
    tone: "good",
    shown: ({ now }) => count(now.won),
    compare: (outcomes) => outcomes.won,
    note: ({ now }) =>
      now.leads_called
        ? `${percent(now.won, now.leads_called)} of ${now.leads_called} leads called`
        : "No leads called yet",
    bars: true,
    day: (day) => day.won,
    seller: (seller) => seller.won,
    sellerWords: (seller) => `${seller.won} won`,
    link: { href: "/leads?tab=all&stage=won", label: "See won leads" },
    explain: "Different leads moved to a won stage.",
  },
  interested: {
    label: "Interested",
    tone: "violet",
    shown: ({ now }) => count(now.interested),
    compare: (outcomes) => outcomes.interested,
    note: () => "Leads who said they want it",
    bars: true,
    day: (day) => day.interested,
    seller: (seller) => seller.interested,
    sellerWords: (seller) => `${seller.interested} interested`,
    link: {
      href: "/leads?tab=all&stage=interested",
      label: "See interested leads",
    },
    explain: "Different leads moved to an interested or a won stage.",
  },
  new_leads: {
    label: "New leads",
    tone: "teal",
    shown: ({ now }) => count(now.new_leads),
    compare: (outcomes) => outcomes.new_leads,
    note: ({ now }) =>
      now.first_call_minutes !== null
        ? `First call in ${minutesWords(now.first_call_minutes)}`
        : now.new_leads
          ? "None called yet"
          : "None came in",
    day: (day) => day.new_leads,
    link: { href: "/leads?tab=all&stage=new", label: "See new leads" },
    explain:
      "Leads that came in. First call is the middle time from a lead arriving to its first call.",
  },
  connected: {
    label: "Connected",
    tone: "slate",
    shown: ({ now }) =>
      now.calls ? (
        <>
          <Count value={Math.round((now.connected / now.calls) * 100)} />%
        </>
      ) : (
        "–"
      ),
    compare: (outcomes) => outcomes.connected,
    note: ({ now }) =>
      `${now.connected} of ${now.calls} ${now.calls === 1 ? "call" : "calls"}`,
    ring: ({ now }) => [now.connected, now.calls],
    day: (day) => day.connected,
    seller: (seller) => seller.connected,
    sellerWords: (seller) =>
      `${seller.connected} of ${seller.calls} ${seller.calls === 1 ? "call" : "calls"}`,
    link: { href: "/analysis/calls", label: "See calls" },
    explain: "Calls that got through, of all calls the team made.",
  },
  // Operations first (Dipak's brief, 28 Oct 2026): shown only when a set names them.
  untouched: {
    label: "Not yet contacted",
    tone: "teal",
    shown: ({ pipeline }) => count(pipeline.new ?? 0),
    note: () => "Open leads with no call yet",
    link: { href: "/leads?tab=all&stage=new", label: "See them" },
    explain:
      "Open leads still in the new stage, right now, whatever the period.",
  },
  first_call: {
    label: "First call",
    tone: "slate",
    shown: ({ now }) =>
      now.first_call_minutes !== null
        ? minutesWords(now.first_call_minutes)
        : "–",
    note: ({ before, period }) =>
      before.first_call_minutes !== null
        ? `${minutesWords(before.first_call_minutes)} ${period === 1 ? "yesterday" : "the period before"}`
        : "Middle time to the first call",
    link: { href: "/leads?tab=all&stage=new", label: "See new leads" },
    explain: "The middle time from a lead arriving to its first call.",
  },
  calls: {
    label: "Calls made",
    tone: "teal",
    shown: ({ now }) => count(now.calls),
    compare: (outcomes) => outcomes.calls,
    note: ({ now }) => `${now.connected} connected`,
    bars: true,
    day: (day) => day.calls,
    seller: (seller) => seller.calls,
    sellerWords: (seller) =>
      `${seller.calls} ${seller.calls === 1 ? "call" : "calls"}`,
    link: { href: "/analysis/calls", label: "See calls" },
    explain: "Calls the team made, counted the way My day counts them.",
  },
  late: {
    label: "Overdue",
    tone: "warn",
    shown: ({ sellers }) =>
      count(sellers.reduce((sum, seller) => sum + seller.late, 0)),
    note: () => "Calls more than an hour late",
    seller: (seller) => seller.late,
    sellerWords: (seller) => `${seller.late} late`,
    link: { href: "/leads?tab=all&due=late", label: "See late leads" },
    explain: "Open leads whose next call is more than an hour late, right now.",
  },
} satisfies Record<string, TileSpec>;

export type TileKey = keyof typeof TILES;

/** Which tiles Home shows, in order. */
export const TILE_SETS = {
  /** The owner's choice, 28 Oct 2026: outcomes first (B). */
  outcomes: ["won", "interested", "new_leads", "connected"],
  /** Operations first (Dipak's brief): not shown until chosen. */
  operations: ["new_leads", "untouched", "first_call", "calls", "late"],
} as const satisfies Record<string, readonly TileKey[]>;

const ringOf = ([part, whole]: [number, number]) => ({ part, whole });

/**
 * The period switch and the outcome tiles. `performance` is the period's
 * report (null while it loads); `failed` when it didn't load.
 */
export function OutcomeTiles({
  period,
  onPeriod,
  performance,
  failed,
  tiles = TILE_SETS.outcomes,
}: {
  period: Period;
  onPeriod: (next: Period) => void;
  performance: Performance | null;
  failed: boolean;
  /** Which tiles, in order (TILE_SETS). */
  tiles?: readonly TileKey[];
}) {
  const [open, setOpen] = useState<TileKey | null>(null);
  const data: TileData | null =
    performance?.current && performance.previous
      ? {
          now: performance.current,
          before: performance.previous,
          days: performance.daily ?? [],
          sellers: performance.sellers,
          pipeline: performance.pipeline,
          period,
        }
      : null;
  const opened: TileSpec | undefined = open ? TILES[open] : undefined;
  const compared = tiles.some((key) => "compare" in TILES[key]);
  return (
    <>
      <Segmented
        label="Period"
        value={String(period) as "1" | "7" | "30"}
        onChange={(next) => onPeriod(Number(next) as Period)}
        items={PERIODS}
      />
      {data ? (
        <div className={styles.tiles}>
          {tiles.map((key) => {
            const tile: TileSpec = TILES[key];
            return (
              <button
                key={key}
                type="button"
                className={styles.tile}
                data-tile={key}
                data-tone={tile.tone}
                aria-haspopup="dialog"
                onClick={() => setOpen(key)}
              >
                <span className={styles.label}>
                  {tile.label}
                  <ChevronRight size={14} aria-hidden="true" />
                </span>
                <span className={styles.figure}>
                  {tile.ring ? <Ring {...ringOf(tile.ring(data))} /> : null}
                  <strong className={styles.value}>{tile.shown(data)}</strong>
                </span>
                {tile.compare ? (
                  <Change
                    value={tile.compare(data.now)}
                    previous={tile.compare(data.before)}
                  />
                ) : (
                  <span className={styles.change} data-trend="flat">
                    Right now
                  </span>
                )}
                {tile.bars && tile.day ? (
                  <DayChart
                    days={data.days}
                    pick={tile.day}
                    label={tile.label}
                  />
                ) : null}
                <span className={styles.note}>{tile.note(data)}</span>
              </button>
            );
          })}
        </div>
      ) : failed ? (
        <p className={styles.quiet} role="status">
          Sales numbers didn&apos;t load. Pull down or come back in a moment.
        </p>
      ) : (
        <OutcomesSkeleton />
      )}
      {data && compared ? (
        <p
          className={styles.footnote}
        >{`Compared with ${beforeWords(period)}`}</p>
      ) : null}
      <Sheet
        open={opened !== undefined}
        onClose={() => setOpen(null)}
        title={opened?.label ?? "Outcome"}
        description={
          period === 1 ? "Today" : `The last ${period} days, India time`
        }
        footer={
          opened ? (
            <Link className={styles.sheetAction} href={opened.link.href}>
              {opened.link.label}
              <ChevronRight size={16} aria-hidden="true" />
            </Link>
          ) : null
        }
      >
        {opened && data ? <TileDetail tile={opened} data={data} /> : null}
      </Sheet>
    </>
  );
}

function TileDetail({ tile, data }: { tile: TileSpec; data: TileData }) {
  const { seller, sellerWords } = tile;
  const ranked =
    seller && sellerWords
      ? data.sellers
          .filter((each) => seller(each) > 0)
          .sort((a, b) => seller(b) - seller(a))
      : [];
  const was = tile.compare?.(data.before);
  return (
    <div className={styles.detail} data-tone={tile.tone}>
      <p className={styles.detailFigure}>
        <strong>{tile.shown(data)}</strong>
        <span>{tile.note(data)}</span>
      </p>
      {tile.compare && was !== undefined ? (
        <p className={styles.detailChange}>
          <Change value={tile.compare(data.now)} previous={was} />
          {` than ${beforeWords(data.period)} (${was})`}
        </p>
      ) : null}
      {tile.day ? (
        <DayChart days={data.days} pick={tile.day} label={tile.label} large />
      ) : null}
      <p className={styles.explain}>{tile.explain}</p>
      {seller && sellerWords ? (
        <section aria-label="By seller">
          <h3 className={styles.detailHead}>By seller</h3>
          {ranked.length ? (
            <ol className={styles.sellers}>
              {ranked.map((each) => (
                <li key={each.person_id}>
                  <Link href={`/organisation/people/${each.person_id}`}>
                    <Avatar name={each.name} size={30} />
                    <span>{each.name}</span>
                    <strong>{sellerWords(each)}</strong>
                    <ChevronRight size={15} aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ol>
          ) : (
            <p className={styles.explain}>None yet in this period.</p>
          )}
        </section>
      ) : null}
    </div>
  );
}
