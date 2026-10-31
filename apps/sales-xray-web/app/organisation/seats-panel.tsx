"use client";

/**
 * Seats on the Team tab (owner, 30 Oct 2026: "a proper seats system").
 *
 * For owners, admins and Finance: how many seats the organisation has (paid
 * ones plus free ones from Authority Closers), who holds them (members and
 * pending invites) and how many are free. Removing someone or revoking an
 * invite frees a seat for someone else; the owner and Finance buy more on the
 * Plan & billing page. People who see the team also see each member's calls,
 * call minutes and last activity, quietest first, to decide whose seat to
 * reassign (SeatUsePanel, below People). Never a price or an end date (Admin
 * only).
 */
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { callDate } from "../call-status";
import { useDisplayDates } from "../display-clock";
import { PersonDisplayName } from "./people/person-display-name";
import {
  notLive,
  readSeats,
  type OrgMember,
  type OrgSeats,
} from "./organisation-api";
import type { Effort } from "../performance/performance-client";
import styles from "./seats.module.css";

/** Where the owner and Finance buy seats (the hub's Plan & billing tab). */
export const BUY_SEATS_HREF = "/settings/plan";
/** No sign-in or call for this long marks a seat as quiet. */
export const QUIET_DAYS = 14;

export type SeatUse = { calls: number; minutes: number };

const plural = (value: number, one: string, many = `${one}s`) =>
  `${value.toLocaleString("en-IN")} ${value === 1 ? one : many}`;

/** Where the seats come from, in one plain line. */
export function seatSource(seats: OrgSeats): string {
  const { paidSeats: paid, complimentarySeats: free } = seats;
  if (paid && free)
    return `${plural(paid, "paid seat")} and ${plural(free, "free seat")} from Authority Closers`;
  if (free) return `${plural(free, "free seat")} from Authority Closers`;
  return plural(paid, "paid seat");
}

/** "active today", "active yesterday", "active on 12 Oct". */
const activeOn = (day: string) =>
  day === "Today" || day === "Yesterday"
    ? `active ${day.toLowerCase()}`
    : `active on ${day}`;

const quietSince = (member: OrgMember, now: number) => {
  const last = Date.parse(member.lastActiveAt ?? member.joinedAt ?? "");
  return Number.isFinite(last) ? now - last : Number.POSITIVE_INFINITY;
};

/**
 * Why an invite can't go out now, or null when a seat is free or there is no
 * seat limit (persona QA, 1 Nov 2026: "No seats yet" sat above a live Invite
 * box, and the server refused every invite). Unknown counts never block.
 */
export function inviteBlock(seats: OrgSeats | null): string | null {
  if (!seats || seats.exempt || seats.seatsAvailable > 0) return null;
  if (seats.totalSeats === 0)
    return seats.canBuy
      ? "No seats yet, so invites can't go out. Buy seats to invite your team."
      : "No seats yet, so invites can't go out. Ask your owner to add seats.";
  return "Every seat is taken. Remove someone or revoke an invite to free one.";
}

export function SeatsPanel({
  version,
  onSeats,
}: {
  /** Changes after a member change, so the counts are read again. */
  version: number;
  /** The counts as read (null when unknown); pass a stable setter. */
  onSeats?: (seats: OrgSeats | null) => void;
}) {
  // "off": a server without seats yet shows nothing, as before.
  const [seats, setSeats] = useState<OrgSeats | "error" | "off" | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    readSeats(controller.signal).then(
      (value) => {
        if (controller.signal.aborted) return;
        setSeats(value);
        onSeats?.(value);
      },
      (error) => {
        if (controller.signal.aborted) return;
        setSeats(notLive(error) ? "off" : "error");
        onSeats?.(null);
      },
    );
    return () => controller.abort();
  }, [version, attempt, onSeats]);

  if (seats === "off") return null;
  if (seats === null)
    return (
      <section className={styles.section} aria-label="Seats" aria-busy="true">
        <div className={styles.card} data-loading="">
          <span className={styles.skeletonLine} />
          <span className={styles.meter} />
          <span className={styles.skeletonLine} data-short="" />
        </div>
      </section>
    );
  if (seats === "error")
    return (
      <section className={styles.section} aria-labelledby="org-seats">
        <h2 id="org-seats" className={styles.title}>
          Seats
        </h2>
        <div className={styles.card}>
          <p className={styles.note}>Seats could not be loaded.</p>
          <button
            type="button"
            className={styles.chip}
            onClick={() => {
              setSeats(null);
              setAttempt((value) => value + 1);
            }}
          >
            <RefreshCw size={14} aria-hidden="true" />
            Try again
          </button>
        </div>
      </section>
    );

  const taken = seats.activeMembers + seats.pendingInvites;
  if (seats.exempt) return <NoSeatLimit seats={seats} />;
  // Members beyond the seats (a free grant ended) still count in full.
  const scale = Math.max(seats.totalSeats, taken, 1);
  const share = (value: number) => `${(value / scale) * 100}%`;
  const full = seats.totalSeats > 0 && seats.seatsAvailable === 0;
  const buy = seats.canBuy ? (
    <Link href={BUY_SEATS_HREF} prefetch={false} className={styles.chip}>
      Buy seats
    </Link>
  ) : null;

  return (
    <section className={styles.section} aria-labelledby="org-seats">
      <div className={styles.head}>
        <h2 id="org-seats" className={styles.title}>
          Seats
        </h2>
        {seats.totalSeats > 0 ? (
          <span className={styles.summary}>
            {taken.toLocaleString("en-IN")} of{" "}
            {plural(seats.totalSeats, "seat")} taken
          </span>
        ) : null}
      </div>
      <div className={styles.card}>
        {seats.totalSeats === 0 ? (
          <div className={styles.empty}>
            <p>
              <b>No seats yet.</b>{" "}
              {seats.canBuy
                ? "Buy seats to invite your team."
                : "Ask your owner to add seats, then invite your team."}
            </p>
            {buy}
          </div>
        ) : (
          <>
            <div
              className={styles.meter}
              role="img"
              aria-label={`${taken} of ${seats.totalSeats} seats taken: ${plural(seats.activeMembers, "member")}, ${plural(seats.pendingInvites, "invite")} waiting, ${seats.seatsAvailable} free`}
            >
              <i
                data-part="members"
                style={{ width: share(seats.activeMembers) }}
              />
              <i
                data-part="invites"
                style={{ width: share(seats.pendingInvites) }}
              />
            </div>
            <ul className={styles.legend}>
              <li data-part="members">
                {plural(seats.activeMembers, "member")}
              </li>
              <li data-part="invites">
                {plural(seats.pendingInvites, "invite")} waiting
              </li>
              <li data-part="free">
                {seats.seatsAvailable.toLocaleString("en-IN")} free
              </li>
            </ul>
            <div className={styles.foot}>
              <p className={styles.note}>
                {full
                  ? "Every seat is taken. Remove someone or revoke an invite to free one."
                  : `${seatSource(seats)}. Removing someone frees their seat for someone else.`}
              </p>
              {buy}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

/**
 * Who uses their seat, below People so Invite stays near the top: each
 * member's calls, call minutes and last activity over 30 days, quietest first.
 */
export function SeatUsePanel({
  people,
  usage,
}: {
  /** Active members, once loaded. */
  people: OrgMember[] | null;
  /** Calls and call minutes per person over the last 30 days, once loaded. */
  usage: Map<string, SeatUse> | null;
}) {
  const dates = useDisplayDates();
  const [now] = useState(() => Date.now());
  const holders = people ? quietestFirst(people, now) : [];
  if (!holders.length) return null;
  return (
    <section className={styles.section} aria-labelledby="org-seat-use">
      <div className={styles.head}>
        <h2 id="org-seat-use" className={styles.title}>
          Seat use
        </h2>
        <span className={styles.summary}>Last 30 days, quietest first</span>
      </div>
      <div className={styles.card} data-list="">
        <ul className={styles.holders} aria-label="Seat use, quietest first">
          {holders.map((member) => {
            const use = usage?.get(member.personId ?? "");
            const quiet = quietSince(member, now) > QUIET_DAYS * 86_400_000;
            const calls = use?.calls ?? member.calls30d;
            const name = member.name || member.email || "Unnamed member";
            return (
              <li key={member.personId} className={styles.holder}>
                <span className={styles.holderName}>
                  <b>
                    <PersonDisplayName name={name} />
                  </b>
                  {quiet ? <span className={styles.quiet}>Quiet</span> : null}
                </span>
                <small>
                  {[
                    plural(calls, "call"),
                    use
                      ? `${Math.round(use.minutes).toLocaleString("en-IN")} min`
                      : null,
                    member.lastActiveAt
                      ? activeOn(
                          callDate(member.lastActiveAt, undefined, dates),
                        )
                      : "not active yet",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </small>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

/**
 * An organisation the exemption covers: invites need no seat, so the card
 * says so instead of counting seats it doesn't need (owner order, 30 Oct).
 */
function NoSeatLimit({ seats }: { seats: OrgSeats }) {
  return (
    <section className={styles.section} aria-labelledby="org-seats">
      <div className={styles.head}>
        <h2 id="org-seats" className={styles.title}>
          Seats
        </h2>
        <span className={styles.summary}>No seat limit</span>
      </div>
      <div className={styles.card}>
        <ul className={styles.legend}>
          <li data-part="members">{plural(seats.activeMembers, "member")}</li>
          <li data-part="invites">
            {plural(seats.pendingInvites, "invite")} waiting
          </li>
        </ul>
        <p className={styles.note}>
          <b>No seat limit.</b> Invite as many people as you need.
        </p>
      </div>
    </section>
  );
}

/** Active members, the longest quiet first, so a seat to reassign is near the top. */
export function quietestFirst(people: OrgMember[], now: number): OrgMember[] {
  return people
    .filter((member) => member.status === "active")
    .sort(
      (a, b) =>
        quietSince(b, now) - quietSince(a, now) ||
        (a.name ?? a.email ?? "").localeCompare(b.name ?? b.email ?? ""),
    );
}

/**
 * Each member's seat use: the calls and talk minutes Analytics counts (the
 * lead desk's own, last 30 days), never fewer than their analysed calls
 * (persona QA, 31 Oct 2026: Seat use said 0 where Analytics said 343).
 */
export function seatUseFrom(
  analysed:
    | readonly { personId: string; calls: number; minutes: number }[]
    | null,
  desk: Effort | null,
): Map<string, SeatUse> | null {
  if (!analysed && !desk) return null;
  const use = new Map<string, SeatUse>(
    (analysed ?? []).map((member) => [
      member.personId,
      { calls: member.calls, minutes: member.minutes },
    ]),
  );
  for (const seller of desk?.sellers ?? []) {
    const had = use.get(seller.person_id);
    use.set(seller.person_id, {
      calls: Math.max(
        seller.inbound.attempted + seller.cold.attempted,
        had?.calls ?? 0,
      ),
      minutes: Math.max(
        (seller.inbound.talk_seconds + seller.cold.talk_seconds) / 60,
        had?.minutes ?? 0,
      ),
    });
  }
  return use;
}
