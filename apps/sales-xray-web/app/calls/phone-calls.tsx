"use client";

/**
 * Your calls, first on Calls (owner, 27 Oct 2026: "There has to be a very
 * easy way to see all call logs, call recordings… it's hidden somewhere" and
 * "it's really hard for her to see who she called"). The calls you made or
 * took with your leads this week, newest first, missed and incoming ones too
 * (the phone app puts dialer calls on their lead by itself). A tap opens the
 * call's Report when it has one, otherwise the lead at that call. With them,
 * the recordings the phone holds for analysis and the work calls from numbers
 * that aren't leads yet. Saved calls follow on the page. It reuses My work's
 * read (GET /v1/lead-desk/activity) and Leads' phone cards; nothing new.
 */

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AddLeadDialog } from "../leads/capture-dialogs";
import { handOverLead } from "../leads/lead-handoff";
import { forgetUnknown } from "../leads/native-phone";
import { PhoneLogCard } from "../leads/phone-log-card";
import { RecordedCallsCard } from "../leads/recorded-calls";
import { UnknownCallsCard } from "../leads/unknown-calls-card";
import { Skeleton } from "../ui/kit";
import {
  CallRows,
  filterTitle,
  inFilter,
  rowFromActivity,
  rowFromTheirs,
  useGo,
  useWeekActivity,
  weekCalls,
  answersFor,
  type CallsFilter,
} from "./call-rows";
import styles from "./phone-calls.module.css";

export { callLine, callsFilter, dayLabel, weekCalls } from "./call-rows";

/** Calls on the Calls page; the rest are in My work, with notes and moves. */
export const SHOWN_CALLS = 6;
const MY_WORK = "/leads?tab=work";

/** Three rows in the list's final shape while the calls load. */
export function CallRowsSkeleton({
  label,
  rows = 3,
}: {
  label: string;
  rows?: number;
}) {
  return (
    <ol className={styles.list} aria-busy="true" aria-label={label}>
      {Array.from({ length: rows }, (_, index) => (
        <li key={index} className={styles.skeleton}>
          <Skeleton width={36} height={36} radius="circle" />
          <span>
            <Skeleton width="55%" height={14} />
            <Skeleton width="35%" height={12} />
          </span>
        </li>
      ))}
    </ol>
  );
}

export function PhoneCalls({
  onSettled,
  filter = null,
  query = "",
}: {
  /** Opened from a number on Home or Team (owner, 2 Nov 2026): that day's
   *  calls with that outcome, all of them, and nothing else. */
  filter?: CallsFilter | null;
  /** Words to find (header search's "Search calls for …", the page's box):
   *  this week's calls whose lead's name has them, all of them (Redmi QA
   *  batch 8, 13 Nov 2026: only the saved calls far below kept the words, so
   *  the search looked dropped). */
  query?: string;
  /** Told once the week's calls answered (or failed): the Calls page then
   *  shows what follows, so nothing below moves as the list fills in. */
  onSettled?: () => void;
} = {}) {
  const go = useGo();
  const [week, retry] = useWeekActivity(filter);
  const settled = week.status !== "loading";
  useEffect(() => {
    if (settled) onSettled?.();
  }, [settled, onSettled]);
  const [unknown, setUnknown] = useState<string | null>(null);
  const [now] = useState(() => new Date());

  if (week.status === "off") return null;
  const words = query.trim();
  const needle = words.toLocaleLowerCase();
  const calls =
    week.status === "ready"
      ? weekCalls(week.items).filter(
          (item) =>
            (!filter || inFilter(item, filter)) &&
            (!needle || item.lead_name.toLocaleLowerCase().includes(needle)),
        )
      : [];
  // Narrowed by a number or by words: every one, and only what's asked.
  const narrowed = Boolean(filter || needle);
  const items = narrowed ? calls : calls.slice(0, SHOWN_CALLS);
  // A call the phone couldn't tell the end of reads as its seller answered it.
  const answers: ReturnType<typeof answersFor> =
    week.status === "ready" ? answersFor(week.items) : new Map();
  const more =
    !narrowed &&
    week.status === "ready" &&
    (calls.length > SHOWN_CALLS || week.more);
  const theirs = Boolean(filter?.person || filter?.team);

  return (
    <section className={styles.calls} aria-labelledby="your-calls-title">
      <div className={styles.head}>
        <h2 id="your-calls-title">
          {filter
            ? filterTitle(filter)
            : needle
              ? `Your calls with “${words}”`
              : "Your calls"}
        </h2>
        {narrowed ? (
          <Link className={styles.more} href="/analysis/calls">
            All calls
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        ) : week.status === "ready" && items.length ? (
          <Link className={styles.more} href={MY_WORK}>
            My work
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        ) : null}
      </div>
      {narrowed ? null : (
        <>
          <PhoneLogCard as="offer" />
          <RecordedCallsCard />
        </>
      )}
      {week.status === "loading" ? (
        <CallRowsSkeleton label="Your calls" />
      ) : week.status === "error" ? (
        <div className={styles.quiet} role="status">
          <span>Your calls didn&apos;t load.</span>
          <button type="button" className={styles.retry} onClick={retry}>
            Try again
          </button>
        </div>
      ) : items.length === 0 && narrowed ? (
        <div className={styles.quiet}>
          <span>
            {needle && !filter
              ? `No calls this week with “${words}”.`
              : "No calls here."}
          </span>
        </div>
      ) : items.length === 0 ? (
        <div className={styles.quiet}>
          <span>
            No calls this week yet. Calls with your leads show here, missed ones
            too.
          </span>
          <Link className={styles.retry} href="/leads">
            Call a lead
          </Link>
        </div>
      ) : (
        <CallRows
          rows={items.map((item) =>
            theirs
              ? rowFromTheirs(item, answers.get(item.event_id) ?? null)
              : rowFromActivity(item, answers.get(item.event_id) ?? null),
          )}
          now={now}
          label="Your calls, newest first"
        />
      )}
      {more ? (
        <Link className={styles.all} href={MY_WORK}>
          See all in My work
        </Link>
      ) : null}
      {narrowed ? null : <UnknownCallsCard onSave={setUnknown} />}
      {unknown ? (
        <AddLeadDialog
          key={`unknown-${unknown}`}
          open
          canManage={false}
          initial={{ name: "", phone: unknown, email: "", note: "" }}
          initialNote="A work call on your phone. Add their name, then add the lead."
          onClose={() => setUnknown(null)}
          onAdded={(leadId) => {
            void forgetUnknown(unknown);
            setUnknown(null);
            handOverLead(leadId);
            go("/leads");
          }}
        />
      ) : null}
    </section>
  );
}
