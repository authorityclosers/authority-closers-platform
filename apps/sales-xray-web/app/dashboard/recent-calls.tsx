"use client";

import { AudioLines, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";

import { callHref, type LibrarySubmission } from "../acquisition-client";
import { callDate, callTone, submissionState } from "../call-status";
import { formatClock } from "../lightbox/time";
import styles from "./recent-calls.module.css";

/** Row height and gap in px; the stylesheet reads them from --row and --gap. */
const ROW = 46;
const GAP = 2;

function callLength(seconds: number): string | null {
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  return formatClock(seconds * 1000).replace(/^0(?=\d:)/, "");
}

/**
 * The dashboard's latest calls as one clean list. It shows only the rows that
 * fit the space left on screen, so the dashboard never scrolls; the rest are
 * one click away in View all calls.
 */
export function RecentCallsList({ calls }: { calls: LibrarySubmission[] }) {
  const listRef = useRef<HTMLUListElement>(null);
  const [fit, setFit] = useState<number | null>(null);

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const height = list.clientHeight;
      setFit(
        height > 0
          ? Math.max(1, Math.floor((height + GAP) / (ROW + GAP)))
          : null,
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(list);
    return () => observer.disconnect();
  }, []);

  const shown = fit === null ? calls : calls.slice(0, fit);
  const hidden = calls.length - shown.length;

  return (
    <div className={styles.root}>
      <ul
        ref={listRef}
        className={styles.list}
        aria-label="Recent calls"
        style={{ "--row": `${ROW}px`, "--gap": `${GAP}px` } as CSSProperties}
      >
        {shown.map((call, index) => {
          const name = call.label?.displayName ?? null;
          const clock = callLength(call.durationSeconds);
          return (
            <li
              key={call.id}
              className={styles.item}
              style={{ "--i": index } as CSSProperties}
            >
              <Link
                href={callHref(call.id)}
                className={styles.row}
                data-tone={callTone(call)}
              >
                <span className={styles.icon} aria-hidden="true">
                  <AudioLines size={15} />
                </span>
                <span
                  className={styles.name}
                  data-untitled={name ? undefined : ""}
                >
                  {name ?? "Untitled call"}
                </span>
                <span className={styles.date}>{callDate(call.createdAt)}</span>
                <span
                  className={styles.length}
                  title={clock ? `About ${clock} long` : "Length unknown"}
                >
                  {clock ?? "—"}
                </span>
                <span className={styles.status} data-tone={callTone(call)}>
                  <i aria-hidden="true" />
                  {submissionState(call)}
                </span>
                <ChevronRight
                  className={styles.chevron}
                  size={16}
                  aria-hidden="true"
                />
              </Link>
            </li>
          );
        })}
      </ul>
      {hidden > 0 && (
        <p className={styles.more}>+{hidden} more in View all calls</p>
      )}
    </div>
  );
}
