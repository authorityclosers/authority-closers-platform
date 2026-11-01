"use client";

/**
 * A seller's day (competitor teardown #18, 1 Nov 2026): their calls and the
 * answers after them, in time order, with the breaks between them (red unless
 * the team set them), below their work and red flags. Today, from the work
 * list My work reads (/activity), for owners and managers.
 */

import { useEffect, useState, type ReactNode } from "react";

import { BreakRow } from "../dashboard/home-today";
import { deskRequest } from "../leads/leads-client";
import { Sheet } from "../ui/sheet";
import type { SellerEffort } from "./performance-client";
import styles from "./performance.module.css";

/** What the day's work list carries for each thing done. */
export type DayItem = {
  event_id: string;
  lead_id: string;
  lead_name: string;
  event: {
    kind: string;
    at: string;
    connected?: boolean | null;
    duration_seconds?: number | null;
    stage_label?: string | null;
    reason_label?: string | null;
  };
};

const CLOCK = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});
const DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

/** What a line says: "Call · 3 min", "Call · not connected", "Interested". */
export function happened(event: DayItem["event"]): string {
  if (event.kind === "call") {
    const seconds = event.duration_seconds ?? 0;
    if (event.connected === false) return "Call · not connected";
    return seconds >= 60
      ? `Call · ${Math.round(seconds / 60)} min`
      : seconds > 0
        ? `Call · ${seconds} s`
        : "Call";
  }
  return event.stage_label ?? event.reason_label ?? "Answer saved";
}

export function SellerDay({
  seller,
  onClose,
  children,
}: {
  seller: SellerEffort | null;
  onClose: () => void;
  /** Their work and red flags, above the day. */
  children?: ReactNode;
}) {
  // Keyed by the seller (performance-view.tsx): a new seller starts empty.
  const [items, setItems] = useState<DayItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const person = seller?.person_id ?? null;
  useEffect(() => {
    if (!person) return;
    const controller = new AbortController();
    deskRequest<{ items?: DayItem[] }>(
      `/activity?day=today&person=${encodeURIComponent(person)}`,
      { signal: controller.signal },
    ).then(
      (page) => setItems(Array.isArray(page.items) ? page.items : []),
      () => {
        if (!controller.signal.aborted) setFailed(true);
      },
    );
    return () => controller.abort();
  }, [person]);
  const today = DAY.format(new Date());
  const entries = [
    ...(items ?? [])
      .filter((item) => ["call", "result"].includes(item.event.kind))
      .map((item) => ({ at: item.event.at, item, gap: null })),
    ...(seller?.breaks ?? [])
      .filter((gap) => DAY.format(new Date(gap.start)) === today)
      .map((gap) => ({ at: gap.start, item: null, gap })),
  ].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return (
    <Sheet
      open={seller !== null}
      onClose={onClose}
      title={seller ? `${seller.name}'s day` : ""}
    >
      {children}
      <h3 className={styles.dayTitle}>Today</h3>
      {failed ? (
        <p className={styles.quiet} role="alert">
          Their day didn&apos;t load. Close this and try again.
        </p>
      ) : items === null ? (
        <p className={styles.quiet} role="status">
          Reading their day…
        </p>
      ) : entries.length ? (
        <ol className={styles.timeline} aria-label="Their day">
          {entries.map((entry) =>
            entry.gap ? (
              <BreakRow key={`gap-${entry.gap.start}`} gap={entry.gap} />
            ) : entry.item ? (
              <li key={entry.item.event_id}>
                <time dateTime={entry.at}>
                  {CLOCK.format(new Date(entry.at))}
                </time>
                <span>
                  <strong>{entry.item.lead_name}</strong>{" "}
                  {happened(entry.item.event)}
                </span>
              </li>
            ) : null,
          )}
        </ol>
      ) : (
        <p className={styles.quiet}>No calls yet today.</p>
      )}
    </Sheet>
  );
}
