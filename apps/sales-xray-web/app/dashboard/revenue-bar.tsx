"use client";

/**
 * The month's revenue bar at the top of Home (owner meeting, 28 Oct 2026, Dipak's
 * idea: "Show it on Home as a small animated bar"). Me: my month against my
 * target, a tick where the month is, and about how many calls a day it takes.
 * Team: the organisation's month; a tap opens each seller's, by name, never
 * ranked. Nothing shows while it loads or with no target set. The Home session
 * mounts it (sales-home.tsx) as Home's first child.
 */

import { ChevronRight } from "lucide-react";
import { useEffect, useState, type CSSProperties } from "react";

import { Sheet } from "../ui/sheet";
import {
  inr,
  monthName,
  readRevenue,
  REVENUE_CHANGED,
  type Revenue,
  type SellerRevenue,
} from "./revenue-client";
import styles from "./revenue.module.css";

type Tone = "done" | "behind" | "on";

/** Ahead of the month or on it, behind it, or there. */
export function toneOf(won: number, target: number, monthGone: number): Tone {
  if (won >= target) return "done";
  return won / target + 0.05 < monthGone ? "behind" : "on";
}

/** Days left in the month, today included (India time); none once it is
 *  past, all of it before it starts. */
export function daysLeft(month: string, now: Date = new Date()): number {
  const [year, number] = month.split("-").map(Number);
  const today = new Date(
    now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const length = new Date(year, number, 0).getDate();
  const here = today.getFullYear() * 12 + today.getMonth();
  const there = year * 12 + number - 1;
  if (here > there) return 0;
  if (here < there) return length;
  return length - today.getDate() + 1;
}

/** The bar's line (competitor teardown #8, 1 Nov 2026): "₹3.2 L to go · 18
 *  days", the working days left when the team's hours say which. */
export function goLine(revenue: Revenue): string | null {
  if (revenue.target === null) return null;
  if (revenue.won >= revenue.target) return "Target reached";
  const days = revenue.needs?.working_days_left ?? daysLeft(revenue.month);
  return `${inr(revenue.target - revenue.won)} to go · ${days} day${days === 1 ? "" : "s"}`;
}

/** On a Monday (India time), the week's pace (competitor teardown #27, 1 Nov
 *  2026): "Week 2: ₹1.1 L of ₹1.25 L pace", what was won against where the
 *  target says the month should be by now. None on other days, or once the
 *  target is reached. */
export function paceLine(
  revenue: Revenue,
  now: Date = new Date(),
): string | null {
  if (revenue.target === null || revenue.won >= revenue.target) return null;
  const local = new Date(
    now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  if (local.getDay() !== 1) return null;
  const week = Math.ceil(local.getDate() / 7);
  const pace = Math.round(revenue.target * revenue.month_gone);
  return `Week ${week}: ${inr(revenue.won)} of ${inr(pace)} pace`;
}

/** What it takes, at the team's own rates: "≈ 6 wins → 20 meetings → 70
 *  interested → 420 calls · 23 a day". */
export function chainLine(needs: NonNullable<Revenue["needs"]>): string {
  const wins = `${needs.wins} win${needs.wins === 1 ? "" : "s"}`;
  return `≈ ${wins} → ${needs.meetings} meetings → ${needs.interested} interested → ${needs.calls} calls · ${needs.calls_per_day} a day`;
}

function Track({ share, monthGone }: { share: number; monthGone: number }) {
  // The fill grows in after the first paint (no motion where it's turned off).
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setShown(share));
    return () => window.cancelAnimationFrame(frame);
  }, [share]);
  return (
    <span
      className={styles.track}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(share * 100)}
    >
      <span
        className={styles.fill}
        style={{ width: `${Math.min(100, shown * 100)}%` }}
      />
      <span
        className={styles.tick}
        style={{ left: `${Math.min(100, monthGone * 100)}%` } as CSSProperties}
        aria-hidden="true"
      />
    </span>
  );
}

function SellerLine({
  seller,
  monthGone,
}: {
  seller: SellerRevenue;
  monthGone: number;
}) {
  const target = seller.target;
  return (
    <li
      className={styles.seller}
      data-tone={target ? toneOf(seller.won, target, monthGone) : undefined}
    >
      <div className={styles.line}>
        <span className={styles.sellerName}>{seller.name}</span>
        <span className={styles.amounts}>
          <strong>{inr(seller.won)}</strong>
          {target ? <span> of {inr(target)}</span> : null}
        </span>
      </div>
      {target ? (
        <Track share={seller.won / target} monthGone={monthGone} />
      ) : null}
      <span className={styles.small}>
        {target
          ? seller.target_source === "own"
            ? "Own target"
            : "Even share"
          : "No target"}
        {seller.amount_not_set
          ? ` · ${seller.amount_not_set} won without an amount`
          : ""}
      </span>
    </li>
  );
}

export function RevenueBar({ scope }: { scope: "mine" | "team" }) {
  const [revenue, setRevenue] = useState<Revenue | null>(null);
  const [open, setOpen] = useState(false);
  // A target saved in Team controls reaches the bar without a reload.
  const [round, setRound] = useState(0);
  useEffect(() => {
    const again = () => setRound((value) => value + 1);
    window.addEventListener(REVENUE_CHANGED, again);
    return () => window.removeEventListener(REVENUE_CHANGED, again);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const read = await readRevenue(scope, controller.signal);
        if (!controller.signal.aborted) setRevenue(read);
      } catch {
        // No bar: Home is never held up by it.
      }
    })();
    return () => controller.abort();
  }, [scope, round]);
  if (!revenue || revenue.target === null || revenue.target <= 0) return null;
  const target = revenue.target;
  const share = revenue.won / target;
  const tone = toneOf(revenue.won, target, revenue.month_gone);
  const needs = revenue.won < target ? revenue.needs : null;
  const pace = paceLine(revenue);
  // A tap shows what it takes, and for the team each seller.
  const opens = !!needs || scope === "team";
  const body = (
    <>
      <span className={styles.line}>
        <span className={styles.amounts}>
          <strong>{goLine(revenue)}</strong>
        </span>
        <span className={styles.percent}>
          {Math.min(999, Math.round(share * 100))}%
        </span>
      </span>
      <Track share={share} monthGone={revenue.month_gone} />
      {pace ? <span className={styles.pace}>{pace}</span> : null}
      <span className={styles.takes}>
        <span>
          {`${inr(revenue.won)} of ${inr(target)} · ${monthName(revenue.month)}`}
        </span>
        {revenue.amount_not_set ? (
          <span className={styles.unset}>
            {revenue.amount_not_set} won without an amount
          </span>
        ) : null}
        {opens ? (
          <span className={styles.more}>
            What it takes
            <ChevronRight size={14} aria-hidden="true" />
          </span>
        ) : null}
      </span>
    </>
  );
  if (!opens)
    return (
      <section
        className={styles.bar}
        data-tone={tone}
        aria-label="This month's revenue"
      >
        {body}
      </section>
    );
  return (
    <>
      <button
        type="button"
        className={styles.bar}
        data-tone={tone}
        aria-haspopup="dialog"
        aria-label={`This month's revenue: ${goLine(revenue)}. What it takes`}
        onClick={() => setOpen(true)}
      >
        {body}
      </button>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title={`${monthName(revenue.month)} revenue`}
      >
        {needs ? (
          <div className={styles.takesBox}>
            <p className={styles.takesWhy}>
              {needs.estimate ? "At typical rates" : "At your 90-day rates"}
            </p>
            <p className={styles.takesChain}>{chainLine(needs)}</p>
          </div>
        ) : null}
        {scope === "team" ? (
          <ul className={styles.sellers}>
            {revenue.sellers.map((seller) => (
              <SellerLine
                key={seller.person_id}
                seller={seller}
                monthGone={revenue.month_gone}
              />
            ))}
          </ul>
        ) : null}
      </Sheet>
    </>
  );
}
