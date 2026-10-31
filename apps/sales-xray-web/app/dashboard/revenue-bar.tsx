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

/** The line under the bar: what it takes to get there. */
export function takesLine(revenue: Revenue): string | null {
  if (revenue.target !== null && revenue.won >= revenue.target)
    return "Target reached";
  const needs = revenue.needs;
  if (!needs) return null;
  if (needs.working_days_left === 0) return "No working days left this month";
  const calls = needs.calls_per_day;
  return `About ${calls} call${calls === 1 ? "" : "s"} a day to get there`;
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
  const takes = takesLine(revenue);
  const body = (
    <>
      <span className={styles.line}>
        <span className={styles.amounts}>
          <strong>{inr(revenue.won)}</strong>
          <span>
            {" "}
            of {inr(target)} · {monthName(revenue.month)}
          </span>
        </span>
        <span className={styles.percent}>
          {Math.min(999, Math.round(share * 100))}%
        </span>
      </span>
      <Track share={share} monthGone={revenue.month_gone} />
      {takes || revenue.amount_not_set || scope === "team" ? (
        <span className={styles.takes}>
          {takes ? <span>{takes}</span> : null}
          {takes && revenue.needs?.estimate && revenue.won < target ? (
            <span className={styles.estimate}>estimate</span>
          ) : null}
          {revenue.amount_not_set ? (
            <span className={styles.unset}>
              {revenue.amount_not_set} won without an amount
            </span>
          ) : null}
          {scope === "team" ? (
            <span className={styles.more}>
              Each seller
              <ChevronRight size={14} aria-hidden="true" />
            </span>
          ) : null}
        </span>
      ) : null}
    </>
  );
  if (scope === "mine")
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
        aria-label={`This month's revenue: ${inr(revenue.won)} of ${inr(target)}. Each seller`}
        onClick={() => setOpen(true)}
      >
        {body}
      </button>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title={`${monthName(revenue.month)} revenue`}
      >
        <ul className={styles.sellers}>
          {revenue.sellers.map((seller) => (
            <SellerLine
              key={seller.person_id}
              seller={seller}
              monthGone={revenue.month_gone}
            />
          ))}
        </ul>
      </Sheet>
    </>
  );
}
