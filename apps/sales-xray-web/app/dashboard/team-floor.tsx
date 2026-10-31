"use client";

/**
 * The team's Home (owner and Dipak, 31 Oct 2026): every figure Dipak's
 * handoff asks of an owner's Home, one lead type at a time, Inbound or Cold,
 * never mixed.
 *
 * - The side's leads: New leads (Inbound) or Unworked (Cold), Open leads,
 *   late follow-ups and leads with no owner, each the count of the exact list
 *   it opens.
 * - Today's calls on that side: tried, connected, not connected, talk time;
 *   then speed: first call (Inbound) or coverage (Cold), Open → Interested,
 *   leads reached, calls without a recording.
 * - Needs you now: what is waiting, worst first, each one tap into its list.
 * - Each seller's day (owners and admins only; sellers never see a ranking):
 *   tries, connects, talk time, the longest break (red when nobody set it)
 *   and the last call.
 *
 * On a phone one column, the figures in a slider; from 1024 px a full-width
 * grid: the work on the left, what needs you on the right.
 */

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { deskRequest, type LeadPage } from "../leads/leads-client";
import {
  readEffort,
  type Effort,
  type SellerEffort,
  type SideEffort,
} from "../performance/performance-client";
import { SideSelector, type Side } from "../ui/side-selector";
import { breakLength } from "./home-today";
import {
  Count,
  MetricPager,
  MoreFigures,
  minutes,
  share,
  type More,
} from "./metric-pager";
import { leadsHref } from "./seller-home";
import styles from "./team-floor.module.css";

/** Today's figures from the Performance engine; null until they arrive. */
function useEffort(): Effort | null {
  const [effort, setEffort] = useState<Effort | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    readEffort(1, controller.signal).then(setEffort, () => undefined);
    return () => controller.abort();
  }, []);
  return effort;
}

type SideCounts = { fresh: number; open: number; unowned: number };

/** The side's three lead counts, each the total of the list its card opens;
 *  read once per side. */
function useSideCounts(side: Side): SideCounts | null {
  const [found, setFound] = useState<Partial<Record<Side, SideCounts>>>({});
  const known = found[side] !== undefined;
  useEffect(() => {
    if (known) return;
    const controller = new AbortController();
    const total = (query: string) =>
      deskRequest<LeadPage>(`/leads?${query}`, {
        signal: controller.signal,
      }).then((page) => page.total);
    Promise.all([
      total(`scope=team&side=${side}&view=to_call&step=new`),
      total(`scope=team&side=${side}&step=open_leads`),
      total(`scope=unassigned&side=${side}`),
    ]).then(
      ([fresh, open, unowned]) =>
        setFound((was) => ({ ...was, [side]: { fresh, open, unowned } })),
      () => undefined,
    );
    return () => controller.abort();
  }, [side, known]);
  return found[side] ?? null;
}

const count = (value: number | undefined | null) =>
  value === undefined || value === null ? null : String(value);

const LATE = (side: Side) =>
  `/leads?tab=all&due=late${side === "cold" ? "&side=cold" : ""}`;

/** An unexplained gap of an hour or more: red. */
const longGap = (seller: SellerEffort) =>
  seller.breaks.some((gap) => !gap.planned && gap.minutes >= 60);

type Need = { key: string; count: number; label: string; href: string };

/** What is waiting on the owner, worst first; only what is above zero. */
function needs(
  side: Side,
  counts: SideCounts | null,
  effort: Effort | null,
): Need[] {
  const day = effort?.[side];
  const list: Need[] = [
    side === "inbound" && counts
      ? {
          key: "fresh",
          count: counts.fresh,
          label: "new enquiries not called yet",
          href: leadsHref("inbound", { view: "to_call", step: "new" }),
        }
      : null,
    side === "inbound" && effort
      ? {
          key: "missed",
          count: effort.inbound.not_called_back,
          label: "missed calls not called back",
          href: leadsHref("inbound", { view: "to_call" }),
        }
      : null,
    day
      ? {
          key: "late",
          count: day.late,
          label: "follow-ups late",
          href: LATE(side),
        }
      : null,
    counts
      ? {
          key: "unowned",
          count: counts.unowned,
          label: "leads with no owner",
          href: `/leads?tab=all&stage=open&who=unassigned${side === "cold" ? "&side=cold" : ""}`,
        }
      : null,
    effort
      ? {
          key: "gaps",
          count: effort.sellers.filter(longGap).length,
          label: "sellers with a 1h+ unexplained break",
          href: "/growth",
        }
      : null,
    effort
      ? {
          key: "recordings",
          count: effort.missing_recordings,
          label: "connected calls without a recording",
          href: "/analysis/calls",
        }
      : null,
  ].filter((need): need is Need => !!need && need.count > 0);
  return list;
}

function pages(
  side: Side,
  counts: SideCounts | null,
  day: SideEffort | null,
): { leads: More[]; calls: More[]; speed: More[] } {
  const cold = side === "cold";
  return {
    leads: [
      {
        key: "new",
        label: cold ? "Unworked" : "New leads",
        value: count(counts?.fresh),
        red: (counts?.fresh ?? 0) > 0,
        href: leadsHref(side, { view: "to_call", step: "new" }),
        help: cold
          ? "Cold leads nobody has called yet"
          : "Enquiries waiting for their first call",
      },
      {
        key: "open",
        label: "Open leads",
        value: count(counts?.open),
        href: leadsHref(side, { view: "all", step: "open_leads" }),
        help: "Leads called and still in discussion",
      },
      {
        key: "late",
        label: "Follow-ups late",
        value: count(day?.late),
        red: (day?.late ?? 0) > 0,
        href: LATE(side),
        help: "Follow-ups more than an hour past their time",
      },
      {
        key: "unowned",
        label: "No owner",
        value: count(counts?.unowned),
        red: (counts?.unowned ?? 0) > 0,
        href: `/leads?tab=all&stage=open&who=unassigned${cold ? "&side=cold" : ""}`,
        help: "Leads no seller has been given",
      },
    ],
    calls: [
      {
        key: "tried",
        label: "Tried",
        value: count(day?.attempted),
        help: "Calls made today",
      },
      {
        key: "connected",
        label: "Connected",
        value: count(day?.connected),
        note:
          day && day.attempted
            ? share(day.connected, day.attempted)
            : undefined,
        help: "Calls answered today, and their share of the calls made",
      },
      {
        key: "not_connected",
        label: "Not connected",
        value: day ? String(day.attempted - day.connected) : null,
        help: "Calls nobody answered today",
      },
      {
        key: "talk",
        label: "Talk time",
        value: day ? minutes(day.talk_seconds) : null,
        help: "Time spent on answered calls today",
      },
    ],
    speed: [
      cold
        ? {
            key: "coverage",
            label: "Coverage",
            value: day ? share(day.leads_attempted, day.eligible) : null,
            help: "Of the leads open or called today, the share called at least once",
          }
        : {
            key: "first_call",
            label: "First call in",
            value: day
              ? day.first_call_minutes === null
                ? "–"
                : `${day.first_call_minutes} min`
              : null,
            help: "Typical minutes from an enquiry arriving to its first call",
          },
      {
        key: "interested",
        label: "Open → Interested",
        value: day ? share(day.worked_interested, day.leads_attempted) : null,
        help: "Of the leads called today, the share moved to Interested or Won",
      },
      {
        key: "reached",
        label: "Leads reached",
        value: count(day?.reached),
        help: "Different leads spoken to today",
      },
      {
        key: "meetings",
        label: "Meetings",
        value: count(day?.meetings),
        help: "Leads given a meeting today",
      },
    ],
  };
}

const CLOCK = new Intl.DateTimeFormat("en-IN", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

function Sellers({ effort, side }: { effort: Effort | null; side: Side }) {
  if (!effort) return <div className={styles.loading} aria-busy="true" />;
  const sellers = [...effort.sellers].sort(
    (a, b) => b[side].attempted - a[side].attempted,
  );
  if (!sellers.length)
    return <p className={styles.quiet}>No sellers on this side yet.</p>;
  return (
    <div className={styles.table} role="table" aria-label="Each seller today">
      <div className={styles.row} role="row" data-head>
        <span role="columnheader">Seller</span>
        <span role="columnheader">Tried</span>
        <span role="columnheader" title="Connected">
          <span className={styles.long}>Connected</span>
          <span className={styles.short}>Conn.</span>
        </span>
        <span role="columnheader">Talk</span>
        <span role="columnheader" title="Longest break">
          <span className={styles.long}>Longest break</span>
          <span className={styles.short}>Break</span>
        </span>
        <span role="columnheader" data-wide>
          Last call
        </span>
      </div>
      {sellers.map((seller) => {
        const day = seller[side];
        const gap = seller.breaks[0];
        return (
          <Link
            key={seller.person_id}
            className={styles.row}
            role="row"
            href="/growth"
          >
            <span role="cell" className={styles.name}>
              {seller.name}
            </span>
            <span role="cell">{day.attempted}</span>
            <span role="cell">{day.connected}</span>
            <span role="cell">{minutes(day.talk_seconds)}</span>
            <span
              role="cell"
              data-red={(gap && !gap.planned && gap.minutes >= 60) || undefined}
              title={
                gap
                  ? gap.planned
                    ? "Inside a set break"
                    : "Not a set break"
                  : undefined
              }
            >
              {gap ? breakLength(gap.minutes) : "–"}
            </span>
            <span role="cell" data-wide>
              {seller.last_call_at
                ? CLOCK.format(new Date(seller.last_call_at))
                : "–"}
            </span>
          </Link>
        );
      })}
    </div>
  );
}

function Split({ effort }: { effort: Effort | null }) {
  const column = (name: string, day: SideEffort | undefined) => (
    <div className={styles.splitSide}>
      <span className={styles.splitName}>{name}</span>
      <dl>
        <div>
          <dt>Tried</dt>
          <dd>{day ? day.attempted : "–"}</dd>
        </div>
        <div>
          <dt>Connected</dt>
          <dd>{day ? day.connected : "–"}</dd>
        </div>
        <div>
          <dt>Talk</dt>
          <dd>{day ? minutes(day.talk_seconds) : "–"}</dd>
        </div>
      </dl>
    </div>
  );
  return (
    <div className={styles.split}>
      {column("Inbound", effort?.inbound)}
      {column("Cold", effort?.cold)}
    </div>
  );
}

const RING = 2 * Math.PI * 52;

/** The clock, once a minute: the sellers' status rings follow it. */
function useMinute(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

type Pulse = "live" | "recent" | "idle" | "none";

/** On a call in the last 10 minutes, 30 or more since the last, or no call yet. */
function pulse(seller: SellerEffort, now: number): Pulse {
  if (!seller.last_call_at) return "none";
  const minutes = (now - Date.parse(seller.last_call_at)) / 60_000;
  return minutes <= 10 ? "live" : minutes >= 30 ? "idle" : "recent";
}

const PULSE_WORDS: Record<Pulse, string> = {
  live: "on calls now",
  recent: "called in the last 30 minutes",
  idle: "30+ minutes since a call",
  none: "no call yet today",
};

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

/** The floor at a glance: the day's ring and every seller's pulse. */
function FloorHero({ effort, side }: { effort: Effort | null; side: Side }) {
  const now = useMinute();
  const day = effort?.[side] ?? null;
  const done = day && day.eligible ? day.leads_attempted / day.eligible : 0;
  const sellers = effort?.sellers ?? [];
  const live = sellers.filter((seller) => pulse(seller, now) === "live").length;
  return (
    <Link
      className={styles.hero}
      href="/growth"
      aria-label={
        day
          ? `Today on ${side === "cold" ? "Cold" : "Inbound"}: ${day.attempted} calls tried, ${day.connected} connected, ${Math.round(done * 100)}% of the day's leads called; ${live} of ${sellers.length} sellers on calls now`
          : "Today's calls"
      }
    >
      <div className={styles.dayRing} aria-hidden="true">
        <svg viewBox="0 0 120 120">
          <circle className={styles.ringTrack} cx="60" cy="60" r="52" />
          <circle
            className={styles.ringDone}
            cx="60"
            cy="60"
            r="52"
            style={
              {
                "--ring": RING,
                strokeDasharray: RING,
                strokeDashoffset: RING * (1 - done),
              } as CSSProperties
            }
          />
        </svg>
        <div className={styles.ringText}>
          <strong>{day ? <Count value={String(day.attempted)} /> : " "}</strong>
          <span>tried today</span>
        </div>
      </div>
      <div className={styles.heroBody} aria-hidden="true">
        <p className={styles.heroLine}>
          <strong>{day ? <Count value={String(day.connected)} /> : "–"}</strong>{" "}
          connected
          {day && day.attempted ? (
            <span>{` · ${share(day.connected, day.attempted)}`}</span>
          ) : null}
        </p>
        <p className={styles.heroNote}>
          {day
            ? `${Math.round(done * 100)}% of today's leads called · ${minutes(day.talk_seconds)} talk`
            : " "}
        </p>
        {sellers.length ? (
          <div className={styles.avatars}>
            <ul>
              {sellers.slice(0, 7).map((seller) => {
                const state = pulse(seller, now);
                return (
                  <li
                    key={seller.person_id}
                    data-pulse={state}
                    title={`${seller.name}: ${PULSE_WORDS[state]}`}
                  >
                    {initials(seller.name)}
                  </li>
                );
              })}
            </ul>
            <span>
              {live
                ? `${live} on calls now`
                : `${sellers.length} ${sellers.length === 1 ? "seller" : "sellers"}`}
            </span>
          </div>
        ) : null}
      </div>
    </Link>
  );
}

export function TeamFloor({
  side,
  onSide,
  controls,
  outcomes,
  more,
  mine = null,
}: {
  side: Side;
  onSide: (side: Side) => void;
  /** Team controls, for those who manage leads. */
  controls: ReactNode;
  /** How sales are going (the period's outcomes). */
  outcomes: ReactNode;
  /** The ways on: Performance, the team, reports. */
  more: ReactNode;
  /** The owner's own tasks and follow-ups, for those who work leads. */
  mine?: ReactNode;
}) {
  const effort = useEffort();
  const counts = useSideCounts(side);
  const day = effort?.[side] ?? null;
  const figures = pages(side, counts, day);
  const waiting = needs(side, counts, effort);
  return (
    <div className={styles.floor}>
      <div className={styles.main}>
        <section
          className={`${styles.block} ${styles.today}`}
          aria-labelledby="floor-title"
        >
          <div className={styles.head}>
            <h2 id="floor-title">Today</h2>
            {controls}
          </div>
          <SideSelector value={side} onChange={onSide} />
          <FloorHero effort={effort} side={side} />
          <MetricPager
            label="The team's numbers"
            pages={[
              {
                key: "leads",
                label: "Leads",
                content: <MoreFigures figures={figures.leads} />,
              },
              {
                key: "calls",
                label: "Calls today",
                content: <MoreFigures figures={figures.calls} />,
              },
              {
                key: "speed",
                label: side === "cold" ? "Coverage" : "Speed",
                content: <MoreFigures figures={figures.speed} />,
              },
            ]}
          />
        </section>
        <section
          className={`${styles.block} ${styles.sellers}`}
          aria-labelledby="sellers-title"
        >
          <div className={styles.head}>
            <h2 id="sellers-title">Each seller today</h2>
            <Link className={styles.seeAll} href="/growth">
              See details
              <ChevronRight size={16} aria-hidden="true" />
            </Link>
          </div>
          <Sellers effort={effort} side={side} />
        </section>
        <section
          className={`${styles.block} ${styles.sales}`}
          aria-labelledby="sales-title"
        >
          <div className={styles.head}>
            <h2 id="sales-title">How sales are going</h2>
          </div>
          {outcomes}
        </section>
      </div>
      <aside className={styles.side} aria-label="Needs you">
        <section
          className={`${styles.block} ${styles.needsBlock}`}
          aria-labelledby="needs-title"
        >
          <div className={styles.head}>
            <h2 id="needs-title">Needs you now</h2>
          </div>
          {waiting.length ? (
            <ul className={styles.needs}>
              {waiting.map((need, index) => (
                <li key={need.key} data-extra={index >= 3 || undefined}>
                  <Link
                    className={styles.need}
                    href={need.href}
                    data-need={need.key}
                  >
                    <strong>{need.count}</strong>
                    <span>{need.label}</span>
                    <ChevronRight size={18} aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.quiet}>
              {effort && counts ? "Nothing waiting. All clear." : " "}
            </p>
          )}
        </section>
        {mine ? <div className={styles.mineBlock}>{mine}</div> : null}
        <section
          className={`${styles.block} ${styles.splitBlock}`}
          aria-labelledby="split-title"
        >
          <div className={styles.head}>
            <h2 id="split-title">Inbound and Cold today</h2>
          </div>
          <Split effort={effort} />
        </section>
        {more}
      </aside>
    </div>
  );
}
