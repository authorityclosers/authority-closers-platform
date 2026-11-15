"use client";

/**
 * A seller's own past (owner, 15 Nov 2026: "sellers should also be able to
 * know their own past"). A small date pill beside Today's overview opens the
 * day picker; a past day opens that day's numbers in a sheet over Home, for
 * the side being looked at. Home itself stays on today.
 */

import {
  CalendarDays,
  Clock,
  PhoneCall,
  PhoneIncoming,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  readEffort,
  type Effort,
  type SideEffort,
} from "../performance/performance-client";
import type { Side } from "../ui/side-selector";
import { Sheet } from "../ui/sheet";
import { DaySheet } from "./day-sheet";
import { dayName } from "./home-day";
import styles from "./my-past-day.module.css";

const talk = (seconds: number) => {
  const minutes = Math.round(seconds / 60);
  return minutes < 60
    ? { value: String(minutes), unit: "min" }
    : { value: `${Math.floor(minutes / 60)}h ${minutes % 60}`, unit: "min" };
};

/** What a past day's sheet counts: the person's own day. */
type OwnDay = Pick<
  SideEffort,
  | "attempted"
  | "connected"
  | "talk_seconds"
  | "reached"
  | "interested"
  | "meetings"
  | "won"
>;

const NO_CALLS: OwnDay = {
  attempted: 0,
  connected: 0,
  talk_seconds: 0,
  reached: 0,
  interested: 0,
  meetings: 0,
  won: 0,
};

/** The signed-in person's own day on this side (Codex review on PR #617): an
 *  owner's, admin's or manager's read is the team's, so their own row is picked
 *  by id; with no row they made no calls that day. A seller's read is their own. */
export function ownDay(effort: Effort, side: Side, me: string | null): OwnDay {
  if (!effort.team) return effort.sellers[0]?.[side] ?? effort[side];
  const row = me
    ? effort.sellers.find((seller) => seller.person_id === me)
    : undefined;
  return row ? row[side] : NO_CALLS;
}

export function PastDayButton({
  side,
  me,
}: {
  side: Side;
  /** The signed-in person, whose day the sheet shows. */
  me: string | null;
}) {
  const [picking, setPicking] = useState(false);
  const [day, setDay] = useState<string | null>(null);
  return (
    <>
      <button
        type="button"
        className={styles.pill}
        aria-label="See another day"
        onClick={() => setPicking(true)}
      >
        <CalendarDays size={16} aria-hidden="true" />
        <span>Past days</span>
      </button>
      <DaySheet
        open={picking}
        onClose={() => setPicking(false)}
        day={null}
        onPick={(next) => setDay(next)}
      />
      <PastDaySheet
        day={day}
        side={side}
        me={me}
        onClose={() => setDay(null)}
      />
    </>
  );
}

function PastDaySheet({
  day,
  side,
  me,
  onClose,
}: {
  day: string | null;
  side: Side;
  me: string | null;
  onClose: () => void;
}) {
  const [got, setGot] = useState<{
    day: string;
    effort: Effort | null;
    failed: boolean;
  } | null>(null);
  useEffect(() => {
    if (!day) return;
    const controller = new AbortController();
    readEffort(1, controller.signal, false, day)
      .then((effort) => setGot({ day, effort, failed: false }))
      .catch((error: unknown) => {
        if ((error as { name?: string })?.name !== "AbortError")
          setGot({ day, effort: null, failed: true });
      });
    return () => controller.abort();
  }, [day]);
  const mine = got && got.day === day ? got : null;
  const own: OwnDay | null = mine?.effort
    ? ownDay(mine.effort, side, me)
    : null;
  const pct =
    own && own.attempted
      ? Math.round((own.connected / own.attempted) * 100)
      : 0;
  const time = own ? talk(own.talk_seconds) : null;
  const figures = own
    ? [
        {
          key: "calls",
          icon: PhoneCall,
          value: String(own.attempted),
          unit: "",
          label: "Calls made",
        },
        {
          key: "picked",
          icon: PhoneIncoming,
          value: String(own.connected),
          unit: `${pct}%`,
          label: "Picked up",
        },
        {
          key: "talk",
          icon: Clock,
          value: time!.value,
          unit: time!.unit,
          label: "Talk time",
        },
        {
          key: "reached",
          icon: Users,
          value: String(own.reached),
          unit: "",
          label: "People reached",
        },
      ]
    : null;
  return (
    <Sheet
      open={day !== null}
      onClose={onClose}
      title={day ? `Your day · ${dayName(day)}` : "Your day"}
      description={side === "cold" ? "Cold calls" : "Inbound calls"}
    >
      {mine?.failed ? (
        <p className={styles.note}>
          That day didn&apos;t load. Close this and try again.
        </p>
      ) : !figures ? (
        <ul className={styles.grid} aria-busy="true">
          {[0, 1, 2, 3].map((n) => (
            <li key={n} className={styles.wait} />
          ))}
        </ul>
      ) : (
        <>
          <ul className={styles.grid}>
            {figures.map((figure, n) => {
              const Icon = figure.icon;
              return (
                <li key={figure.key} style={{ animationDelay: `${n * 60}ms` }}>
                  <span className={styles.icon} data-k={figure.key}>
                    <Icon size={16} aria-hidden="true" />
                  </span>
                  <strong>
                    {figure.value}
                    {figure.unit ? <small>{figure.unit}</small> : null}
                  </strong>
                  <span className={styles.label}>{figure.label}</span>
                </li>
              );
            })}
          </ul>
          <dl className={styles.wins}>
            <div>
              <dt>Interested</dt>
              <dd>{own!.interested}</dd>
            </div>
            <div>
              <dt>Meetings</dt>
              <dd>{own!.meetings}</dd>
            </div>
            <div>
              <dt>Won</dt>
              <dd>{own!.won}</dd>
            </div>
          </dl>
        </>
      )}
    </Sheet>
  );
}
