"use client";

/**
 * Recently called (owner, 24 Oct 2026): on a seller's Home, under Today, the
 * leads they last spoke to or tried this week, newest first, each with how it
 * went and when. A tap opens the lead; the phone calls them back in one tap.
 * Nothing shows until there is something to show.
 */

import { ChevronRight, PhoneCall } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import { handOverLead } from "../leads/lead-handoff";
import { ago, readLeads, type LeadRow } from "../leads/leads-client";
import { Avatar } from "../ui/kit";
import { RowsSkeleton } from "./sales-home-skeleton";
import styles from "./sales-home.module.css";

/** Rows on Home; the rest are on Leads, sorted the same way. */
export const RECENT_ROWS = 5;
const ALL_RECENT =
  "/leads?tab=all&stage=open&contact=week&sort=last_contact&order=desc";

/** "Interested · 2h ago": how it went, then when. */
export function recentLine(row: LeadRow, now: Date = new Date()): string {
  const outcome = row.last_result_label ?? row.stage_label;
  return row.last_contact_at
    ? `${outcome} · ${ago(row.last_contact_at, now)}`
    : outcome;
}

export function RecentlyCalled() {
  const [rows, setRows] = useState<LeadRow[] | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    readLeads(
      {
        scope: "mine",
        more: { contact: "week", sort: "last_contact", order: "desc" },
      },
      controller.signal,
    ).then(
      (page) => setRows(page.leads.slice(0, RECENT_ROWS)),
      // Home stays calm: Today above already says when leads don't load.
      () => setRows([]),
    );
    return () => controller.abort();
  }, []);

  if (rows === null) return <RowsSkeleton rows={3} kind="lead" />;
  if (rows.length === 0) return null;
  return (
    <section className={styles.block} aria-labelledby="recent-title">
      <div className={styles.head}>
        <h2 id="recent-title">Recently called</h2>
        <span className={styles.meta}>This week</span>
      </div>
      <ol className={styles.list}>
        {rows.map((row) => {
          const name = displayName(row.name);
          return (
            <li key={row.lead_id} className={styles.recentItem}>
              <Link
                className={styles.row}
                href="/leads"
                onClick={() => handOverLead(row.lead_id)}
              >
                <Avatar name={row.name} size={34} />
                <span className={styles.rowMain}>
                  <strong>{name}</strong>
                  <small>{recentLine(row)}</small>
                </span>
                <ChevronRight size={16} aria-hidden="true" />
              </Link>
              {row.phone_last4 ? (
                <Link
                  className={styles.callBack}
                  href="/leads"
                  aria-label={`Call ${name}`}
                  onClick={() => handOverLead(row.lead_id, true)}
                >
                  <PhoneCall size={18} aria-hidden="true" />
                </Link>
              ) : null}
            </li>
          );
        })}
      </ol>
      <Link className={styles.more} href={ALL_RECENT}>
        See everyone you called this week
      </Link>
    </section>
  );
}
