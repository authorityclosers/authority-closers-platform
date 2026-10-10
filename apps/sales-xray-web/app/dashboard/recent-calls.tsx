"use client";

import { AudioLines, ChevronRight } from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import { callHref, type LibrarySubmission } from "../acquisition-client";
import { unnamedCallName } from "../call-label";
import { ownerLabel } from "../call-ownership";
import { callDate, callTone, submissionState } from "../call-status";
import { formatClock } from "../lightbox/time";
import styles from "./recent-calls.module.css";

/** Row height and gap in px; the stylesheet reads them from --row and --gap. */
const ROW = 44;
const GAP = 0;

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (
    parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
  ).toUpperCase();
}

function callLength(seconds: number): string | null {
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  return formatClock(seconds * 1000).replace(/^0(?=\d:)/, "");
}

/**
 * The dashboard's latest calls as one clean list. It shows only the rows that
 * fit the space left on screen, so the dashboard never scrolls; the rest are
 * one click away in View all calls.
 */
export function RecentCallsList({
  calls,
  onHiddenChange,
  viewerId = null,
}: {
  calls: LibrarySubmission[];
  /** How many calls did not fit, for the card header. */
  onHiddenChange?: (count: number) => void;
  /** The signed-in person, so their own calls read "You". */
  viewerId?: string | null;
}) {
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
  // Owners and admins see the team's calls: then every row says whose.
  const owners = calls.some((call) => call.owner);
  const hidden = calls.length - shown.length;
  useEffect(() => {
    onHiddenChange?.(hidden);
  }, [hidden, onHiddenChange]);

  return (
    <div className={styles.root}>
      <ul
        ref={listRef}
        className={styles.list}
        data-owners={owners ? "" : undefined}
        aria-label="Recent calls"
        style={{ "--row": `${ROW}px`, "--gap": `${GAP}px` } as CSSProperties}
      >
        {shown.map((call, index) => {
          const name = call.label?.displayName ?? null;
          const clock = callLength(call.durationSeconds);
          const owner = owners
            ? call.owner
              ? ownerLabel(call.owner, viewerId)
              : "You"
            : null;
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
                  {name ?? unnamedCallName(call.createdAt)}
                </span>
                {owner ? (
                  <span
                    className={styles.owner}
                    data-mine={owner === "You" ? "" : undefined}
                  >
                    <i aria-hidden="true">
                      {owner === "You" ? "Y" : initials(owner)}
                    </i>
                    <span>{owner}</span>
                  </span>
                ) : null}
                <span className={styles.date}>{callDate(call.createdAt)}</span>
                <span
                  className={styles.length}
                  title={clock ? `${clock} long` : "Length unknown"}
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
    </div>
  );
}

/** Recent calls while the list loads: three rows with the final shape. */
export function RecentCallsSkeleton() {
  return (
    <div className={styles.root} aria-label="Loading recent calls">
      <ul className={styles.list} aria-hidden="true">
        {[46, 30, 58].map((width, index) => (
          <li
            key={width}
            className={styles.skeletonRow}
            style={{ "--i": index, "--w": `${width}%` } as CSSProperties}
          >
            <i />
            <span />
            <em />
          </li>
        ))}
      </ul>
    </div>
  );
}
