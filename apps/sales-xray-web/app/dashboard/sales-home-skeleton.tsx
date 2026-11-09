"use client";

/**
 * Blocks' outlines while they load, in the final layout (Liquid Glass, 22 Oct
 * 2026): each keeps its heading, its card and its rows' height, so only the
 * numbers and names fill in. Each block draws its own while its read is on the
 * way; Home's whole outline is home-outline.tsx.
 */

import { ActionList, ActionRow, Skeleton, SkeletonRow } from "../ui/kit";
import styles from "./sales-home.module.css";

/** A list card's rows: sellers or leads. */
export function RowsSkeleton({
  rows,
  kind,
}: {
  rows: number;
  kind: "seller" | "lead";
}) {
  return (
    <div className={styles.rowsSkeleton} data-kind={kind} aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <SkeletonRow
          key={index}
          avatar={34}
          lines={2}
          end={kind === "seller"}
        />
      ))}
    </div>
  );
}

/**
 * Needs you: the kit's own action rows with their words waiting, so the
 * outline takes each look's frame (cards, or one inset card), icon tile and
 * row height; a summary row's note runs to two lines on a phone.
 */
export function NeedsSkeleton() {
  return (
    <div aria-hidden="true" inert>
      <ActionList>
        {[0, 1].map((index) => (
          <ActionRow
            key={index}
            tone="neutral"
            icon={<span />}
            title={
              <span className={styles.line}>
                <Skeleton width="64%" height={14} />
              </span>
            }
            note={
              <span className={`${styles.line} ${styles.twoLines}`}>
                <Skeleton width="86%" height={11} />
              </span>
            }
            end={<Skeleton width={26} height={22} radius="pill" />}
          />
        ))}
      </ActionList>
    </div>
  );
}

/** The four outcome tiles, each line at its loaded height. */
export function OutcomesSkeleton() {
  return (
    <dl className={styles.outcomes} aria-busy="true">
      {[0, 1, 2, 3].map((index) => (
        <div key={index} className={styles.outcome} data-skeleton="">
          <span className={styles.outcomeIcon}>
            <Skeleton width={36} height={36} />
          </span>
          <dt className={styles.line}>
            <Skeleton width="64%" height={12} />
          </dt>
          <dd>
            <span className={`${styles.outcomeValue} ${styles.line}`}>
              <Skeleton width={44} height={24} />
            </span>
          </dd>
          <dd className={`${styles.outcomeNote} ${styles.line}`}>
            <Skeleton width="78%" height={10} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Open leads by stage: the four stages' own rows, their tracks empty. */
export function FunnelSkeleton() {
  return (
    <ul className={styles.funnel} aria-hidden="true">
      {[0, 1, 2, 3].map((index) => (
        <li key={index}>
          <span className={styles.funnelLine}>
            <span className={`${styles.funnelLabel} ${styles.line}`}>
              <Skeleton width="56%" height={12} />
            </span>
            <span className={styles.funnelTrack} />
            <strong className={`${styles.funnelCount} ${styles.line}`}>
              <Skeleton width={20} height={12} />
            </strong>
          </span>
        </li>
      ))}
    </ul>
  );
}
