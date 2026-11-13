"use client";

/**
 * Growth without tables (owner, 10 Nov 2026, picking from the design page: "G4
 * and G1 are better"). Two views of the same period, one after the other, each
 * its own component so they can later be A/B tested or chosen (GROWTH_VIEWS):
 * - PulseTiles (G1): four equal tiles (attempted, connected, talk time, moved to
 *   Interested), one total each with a line of what is behind it (owner, 10
 *   Nov: "we don't have to focus on inbound and cold leads"), what needs
 *   attention, and each seller's calls.
 * - DayRhythm (G4): only what the tiles don't say (owner, 13 Nov 2026: "drop
 *   the repeats"): talk time by seller on the team's Growth, and when calls
 *   happen (by hour today, by day over 7 days or the month). Attempted,
 *   connected and talk time are the tiles' numbers, so they aren't here again.
 * - SpeedTile (G2's one number, small): how soon new Inbound leads are called.
 * Only real numbers: a missing value is a dash, a real zero shows 0.
 */

import { useEffect, useId, useState, type CSSProperties } from "react";

import { breakLength } from "../dashboard/home-today";
import { displayName } from "../display-name";
import { readDayCalls, type ActivityPage } from "../leads/leads-client";
import type { Effort, SellerEffort, SideEffort } from "./performance-client";
import styles from "./growth-visual.module.css";

/** The views in the order Growth shows them; a test or a choice reorders this. */
export const GROWTH_VIEWS = ["tiles", "rhythm"] as const;
export type GrowthView = (typeof GROWTH_VIEWS)[number];

/** The Growth period: today, 7 days, or this month so far. */
export type GrowthPeriod = "1" | "7" | "month";

type Sides = { inbound: SideEffort; cold: SideEffort };
type Summed =
  | "attempted"
  | "connected"
  | "talk_seconds"
  | "interested"
  | "leads_attempted"
  | "reached"
  | "meetings";

const both = (sides: Sides, key: Summed) =>
  sides.inbound[key] + sides.cold[key];
export const talkTime = (seconds: number) =>
  breakLength(Math.round(seconds / 60));
const number = new Intl.NumberFormat("en-IN");
const n = (value: number) => number.format(value);
/** "1 lead called", "12 leads called". */
const count = (value: number, one: string, many: string) =>
  `${n(value)} ${value === 1 ? one : many}`;
/** "34%", or a dash when there is nothing to divide. */
const share = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : "–";
/** A delay so the parts of one card arrive in turn (none when motion is off). */
const step = (index: number) =>
  ({ "--gv-delay": `${index * 60}ms` }) as CSSProperties;

/** One share as a ring that draws itself, its percent in the middle. */
function Ring({
  part,
  whole,
  label,
}: {
  part: number;
  whole: number;
  label: string;
}) {
  const radius = 18;
  const around = 2 * Math.PI * radius;
  const value = whole > 0 ? Math.min(1, part / whole) : null;
  return (
    <span
      className={styles.ring}
      role="img"
      aria-label={`${label}: ${share(part, whole)}`}
    >
      <svg viewBox="0 0 44 44" aria-hidden="true">
        <circle cx="22" cy="22" r={radius} className={styles.ringTrack} />
        {value ? (
          <circle
            cx="22"
            cy="22"
            r={radius}
            className={styles.ringValue}
            strokeDasharray={around}
            strokeDashoffset={around * (1 - value)}
            transform="rotate(-90 22 22)"
            style={{ "--gv-around": around } as CSSProperties}
          />
        ) : null}
      </svg>
      <span className={styles.ringWords} aria-hidden="true">
        {share(part, whole)}
      </span>
    </span>
  );
}

/** G2's speed to a new lead, small: the median minutes to the first call. */
export function SpeedTile({ effort }: { effort: Effort }) {
  const minutes = effort.inbound.first_call_minutes;
  return (
    <section className={styles.speed} aria-label="Speed to new lead">
      <span className={styles.speedWords}>
        <span className={styles.label}>Speed to new lead</span>
        <span className={styles.meta}>Inbound, median to the first call</span>
      </span>
      <strong className={styles.speedFigure}>
        {minutes === null ? "–" : breakLength(Math.round(minutes))}
      </strong>
    </section>
  );
}

/** What needs someone now: only real counts above zero. */
export function attention(effort: Effort) {
  const { inbound, cold } = effort;
  const rows: {
    key: string;
    label: string;
    value: number;
    hint?: string;
    tone: "late" | "due";
  }[] = [
    {
      key: "late",
      label: "Late follow-ups",
      value: inbound.late + cold.late,
      tone: "late",
    },
    {
      key: "backlog",
      label: "Not called yet",
      value: inbound.backlog + cold.backlog,
      tone: "due",
    },
    {
      key: "missed",
      label: "Missed calls",
      value: inbound.missed_calls + cold.missed_calls,
      tone: "due",
    },
    {
      key: "recordings",
      label: "Calls without a recording",
      value: effort.missing_recordings,
      tone: "due",
    },
  ];
  return rows.filter((row) => row.value > 0);
}

const sellerCalls = (seller: SellerEffort) => both(seller, "attempted");

/** One seller's numbers as G1's tiles read them, for their day's sheet. */
export function sellerEffort(seller: SellerEffort): Effort {
  return {
    days: 1,
    start: "",
    end: "",
    team: false,
    sellers: [seller],
    inbound: seller.inbound,
    cold: seller.cold,
    missing_recordings: seller.missing_recordings,
  };
}

/** G1: four equal tiles, what needs attention, and each seller's calls. */
export function PulseTiles({
  effort,
  onOpen,
  title,
}: {
  effort: Effort;
  onOpen?: (seller: SellerEffort) => void;
  /** The heading: Team, Your work, or a seller's own in their day's sheet. */
  title?: string;
}) {
  const headingId = useId();
  const attempted = both(effort, "attempted");
  const connected = both(effort, "connected");
  const talked = both(effort, "talk_seconds");
  const needs = attention(effort);
  const sellers = [...effort.sellers].sort(
    (a, b) => sellerCalls(b) - sellerCalls(a),
  );
  const most = Math.max(1, ...sellers.map(sellerCalls));
  const working = sellers.filter((seller) => sellerCalls(seller) > 0);
  const idle = sellers.length - working.length;
  return (
    <section
      className={styles.view}
      data-growth-view="tiles"
      aria-labelledby={headingId}
    >
      <h2 id={headingId} className={styles.heading}>
        {title ?? (effort.team ? "Team" : "Your work")}
      </h2>
      {/* One total a tile, no Inbound | Cold split (owner, 10 Nov 2026: "we
          don't have to focus on inbound and cold leads"), each with one
          line of what is behind it. */}
      <div className={styles.tiles}>
        <div className={styles.tile} style={step(0)}>
          <span className={styles.label}>Attempted</span>
          <strong className={styles.figure}>{n(attempted)}</strong>
          <span className={styles.meta}>
            {count(
              both(effort, "leads_attempted"),
              "lead called",
              "leads called",
            )}
          </span>
        </div>
        <div className={styles.tile} style={step(1)}>
          <span className={styles.label}>Connected</span>
          <span className={styles.figureRow}>
            <strong className={styles.figure}>{n(connected)}</strong>
            <Ring
              part={connected}
              whole={attempted}
              label="Connected of attempted"
            />
          </span>
          <span className={styles.meta}>
            {count(both(effort, "reached"), "lead reached", "leads reached")}
          </span>
        </div>
        <div className={styles.tile} style={step(2)}>
          <span className={styles.label}>Talk time</span>
          <strong className={styles.figure}>{talkTime(talked)}</strong>
          <span className={styles.meta}>
            {connected
              ? `About ${talkTime(talked / connected)} per connected call`
              : "No connected calls"}
          </span>
        </div>
        <div className={styles.tile} style={step(3)}>
          <span className={styles.label}>Interested</span>
          <strong className={styles.figure}>
            {n(both(effort, "interested"))}
          </strong>
          <span className={styles.meta}>
            {count(
              both(effort, "meetings"),
              "meeting booked",
              "meetings booked",
            )}
          </span>
        </div>
      </div>

      <div className={styles.card}>
        <h3 className={styles.cardTitle}>Needs attention</h3>
        {needs.length ? (
          <ul className={styles.needs}>
            {needs.map((row) => (
              <li key={row.key} data-tone={row.tone}>
                <span className={styles.needWords}>
                  <span>{row.label}</span>
                  {row.hint ? (
                    <span className={styles.meta}>{row.hint}</span>
                  ) : null}
                </span>
                <b>{n(row.value)}</b>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.meta}>Nothing needs attention.</p>
        )}
      </div>

      {effort.team && sellers.length ? (
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>Each seller</h3>
          {/* Sellers with calls get a row; the rest are one line, not a
              column of zeros. */}
          <ul className={styles.sellers} aria-label="Each seller's calls">
            {working.map((seller, index) => {
              const tried = sellerCalls(seller);
              const spoke = both(seller, "connected");
              return (
                <li key={seller.person_id}>
                  <button
                    type="button"
                    className={styles.sellerRow}
                    onClick={() => onOpen?.(seller)}
                    disabled={!onOpen}
                  >
                    <span className={styles.sellerTop}>
                      <span className={styles.sellerName}>
                        {displayName(seller.name)}
                      </span>
                      <span className={styles.meta}>
                        {talkTime(both(seller, "talk_seconds"))}
                      </span>
                    </span>
                    <span
                      className={styles.sellerBar}
                      role="img"
                      aria-label={`${n(tried)} attempted, ${n(spoke)} connected`}
                      style={step(index)}
                    >
                      <span
                        className={styles.sellerTried}
                        style={{ width: `${(tried / most) * 100}%` }}
                      >
                        <span
                          className={styles.sellerSpoke}
                          style={{
                            width: `${tried ? (spoke / tried) * 100 : 0}%`,
                          }}
                        />
                      </span>
                    </span>
                    <span className={styles.meta}>
                      {n(tried)} attempted · {n(spoke)} connected
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {idle ? (
            <p className={styles.meta}>
              {idle === sellers.length
                ? "No calls yet."
                : `${n(idle)} more ${idle === 1 ? "seller" : "sellers"} with no calls yet.`}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/* ---------- When calls happen (G4's fourth card) ---------- */

export type Slot = { key: string; label: string; short: string; calls: number };

const HOUR = (timezone: string) =>
  new Intl.DateTimeFormat("en-GB", {
    hour: "numeric",
    hourCycle: "h23",
    timeZone: timezone,
  });
const hourWords = (hour: number) =>
  `${hour % 12 || 12} ${hour < 12 ? "am" : "pm"}`;

/** Today's calls by hour, from first light to evening (9 am to 7 pm at least). */
export function hourSlots(
  items: ActivityPage["items"],
  timezone = "Asia/Kolkata",
): Slot[] {
  const format = HOUR(timezone);
  const counts = new Map<number, number>();
  for (const item of items) {
    if (item.event.kind !== "call") continue;
    const hour = Number(format.format(new Date(item.event.at)));
    counts.set(hour, (counts.get(hour) ?? 0) + 1);
  }
  const hours = [...counts.keys()];
  const first = Math.min(9, ...hours);
  const last = Math.max(19, ...hours);
  const slots: Slot[] = [];
  for (let hour = first; hour <= last; hour++)
    slots.push({
      key: String(hour),
      label: hourWords(hour),
      short: `${hour % 12 || 12}${hour < 12 ? "a" : "p"}`,
      calls: counts.get(hour) ?? 0,
    });
  return slots;
}

const DAY_WORDS = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});
/** The period's calls by day, from the activity summary's daily counts. */
export function daySlots(
  people: { daily?: { day: string; calls: number }[] }[],
  start: string,
  end: string,
): Slot[] {
  // The summary's daily rows also cover the period before (for its
  // comparison): only the period's own days count, each day drawn, a day
  // with no calls as 0.
  const counts = new Map<string, number>();
  for (const person of people)
    for (const day of person.daily ?? []) {
      const key = day.day.slice(0, 10);
      counts.set(key, (counts.get(key) ?? 0) + day.calls);
    }
  const slots: Slot[] = [];
  const last = Date.parse(`${end.slice(0, 10)}T00:00:00Z`);
  for (
    let at = Date.parse(`${start.slice(0, 10)}T00:00:00Z`);
    at <= last && slots.length < 92;
    at += 86400000
  ) {
    const key = new Date(at).toISOString().slice(0, 10);
    const words = DAY_WORDS.format(new Date(at));
    slots.push({
      key,
      label: words,
      short: words.split(" ")[0],
      calls: counts.get(key) ?? 0,
    });
  }
  return slots;
}

/** Today's calls are read page by page; this many pages at most. */
const PAGES = 12;

type Rhythm =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; slots: Slot[]; byHour: boolean; partial: boolean };

/** The days since the 1st, today included (India time): this month so far. */
const monthDays = () =>
  Number(
    new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      timeZone: "Asia/Kolkata",
    }).format(new Date()),
  );

async function readRhythm(
  period: GrowthPeriod,
  team: boolean,
  signal: AbortSignal,
) {
  if (period === "1") {
    const items: ActivityPage["items"] = [];
    let before: string | null = null;
    let timezone = "Asia/Kolkata";
    for (let page = 0; page < PAGES; page++) {
      const read: ActivityPage = await readDayCalls(
        "today",
        { person: null, team },
        before,
        signal,
      );
      items.push(...read.items);
      timezone = read.timezone ?? timezone;
      before = read.next_before;
      if (!before) break;
    }
    return {
      slots: hourSlots(items, timezone),
      byHour: true,
      partial: before !== null,
    };
  }
  const days = period === "7" ? 7 : monthDays();
  // The team's days for those who see the team, a seller's own otherwise.
  const query = new URLSearchParams({ days: String(days) });
  if (team) query.set("team", "true");
  const response = await fetch(`/v1/lead-desk/activity/summary?${query}`, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json" },
  });
  if (!response.ok) throw new Error("Calls by day could not load");
  const summary = (await response.json()) as {
    start: string;
    today: string;
    people?: { daily?: { day: string; calls: number }[] }[];
  };
  return {
    slots: daySlots(summary.people ?? [], summary.start, summary.today),
    byHour: false,
    partial: false,
  };
}

function useRhythm(period: GrowthPeriod, team: boolean): Rhythm {
  // Each answer is kept with the read it is for, so a new period reads as
  // loading until its own answer lands, with no reset inside the effect.
  const key = `${period}:${team}`;
  const [rhythm, setRhythm] = useState<{ key: string; value: Rhythm }>({
    key,
    value: { status: "loading" },
  });
  useEffect(() => {
    const controller = new AbortController();
    const asked = `${period}:${team}`;
    readRhythm(period, team, controller.signal).then(
      (ready) =>
        setRhythm({ key: asked, value: { status: "ready", ...ready } }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setRhythm({ key: asked, value: { status: "error" } });
      },
    );
    return () => controller.abort();
  }, [period, team]);
  return rhythm.key === key ? rhythm.value : { status: "loading" };
}

/** The busiest slot's words, or null with no calls. */
export function busiest(slots: Slot[]): Slot | null {
  const top = slots.reduce<Slot | null>(
    (best, slot) => (slot.calls > (best?.calls ?? 0) ? slot : best),
    null,
  );
  return top;
}

function RhythmBars({ rhythm }: { rhythm: Rhythm }) {
  if (rhythm.status !== "ready")
    return (
      <div className={styles.bars} data-empty="">
        {rhythm.status === "error" ? (
          <p className={styles.meta} role="alert">
            When calls happen didn&apos;t load.
          </p>
        ) : null}
      </div>
    );
  const { slots } = rhythm;
  const most = Math.max(1, ...slots.map((slot) => slot.calls));
  const every = slots.length > 14 ? 7 : 3;
  // Each bar's number on it, so the chart reads without a tap (Redmi QA on
  // the owner's production build, 13 Nov 2026: bars had no counts). Up to 14
  // bars, every bar with calls; the hours and the month, the busiest only.
  const peak = busiest(slots);
  const counted = (slot: Slot) =>
    slot.calls > 0 && (slots.length <= 14 || slot.key === peak?.key);
  return (
    <div
      className={styles.bars}
      role="img"
      aria-label={slots
        .map((slot) => `${slot.label}: ${n(slot.calls)}`)
        .join(", ")}
    >
      {slots.map((slot, index) => (
        <span key={slot.key} className={styles.barSlot}>
          <span
            className={styles.bar}
            style={{
              ...step(index),
              height: `${Math.max(slot.calls ? 4 : 0, (slot.calls / most) * 100)}%`,
            }}
          >
            {counted(slot) ? (
              <span className={styles.barCount} aria-hidden="true">
                {n(slot.calls)}
              </span>
            ) : null}
          </span>
          <span className={styles.barLabel} aria-hidden="true">
            {index % every === 0 ? slot.short : ""}
          </span>
        </span>
      ))}
    </div>
  );
}

/** G4: four larger cards, each with its own small animation. */
export function DayRhythm({
  effort,
  period,
}: {
  effort: Effort;
  period: GrowthPeriod;
}) {
  const talkers = [...effort.sellers]
    .map((seller) => ({ seller, seconds: both(seller, "talk_seconds") }))
    .filter((row) => row.seconds > 0)
    .sort((a, b) => b.seconds - a.seconds)
    .slice(0, 4);
  const longest = Math.max(1, ...talkers.map((row) => row.seconds));
  const rhythm = useRhythm(period, effort.team);
  const top = rhythm.status === "ready" ? busiest(rhythm.slots) : null;
  return (
    <section
      className={styles.view}
      data-growth-view="rhythm"
      aria-labelledby="growth-rhythm-title"
    >
      <h2 id="growth-rhythm-title" className={styles.heading}>
        Day rhythm
      </h2>
      {/* Each seller's share of the talk time: the team's Growth only, and
          only once someone has talked (a seller's own total is a tile). */}
      {effort.team && talkers.length ? (
        <div className={styles.big} style={step(0)}>
          <span className={styles.label}>Talk time by seller</span>
          <ul className={styles.talkers} aria-label="Talk time by seller">
            {talkers.map(({ seller, seconds }, index) => (
              <li key={seller.person_id}>
                <span className={styles.talkerTop}>
                  <span className={styles.sellerName}>
                    {displayName(seller.name)}
                  </span>
                  <span className={styles.meta}>{talkTime(seconds)}</span>
                </span>
                <span className={styles.talkTrack} aria-hidden="true">
                  <span
                    className={styles.talkBar}
                    style={{
                      ...step(index),
                      width: `${(seconds / longest) * 100}%`,
                    }}
                  />
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className={styles.big} style={step(1)}>
        <span className={styles.label}>
          {period === "1" ? "Calls by hour" : "Calls by day"}
        </span>
        <strong className={styles.bigTitle}>
          {rhythm.status !== "ready"
            ? " "
            : top
              ? `Busiest ${period === "1" ? "at" : "on"} ${top.label}`
              : "No calls yet"}
        </strong>
        <RhythmBars rhythm={rhythm} />
        {rhythm.status === "ready" && rhythm.partial ? (
          <p className={styles.meta}>
            Only the day&apos;s latest calls are counted here.
          </p>
        ) : null}
      </div>
    </section>
  );
}
