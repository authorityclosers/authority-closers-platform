"use client";

/**
 * Home's outline while it loads, in the final layout (Liquid Glass, 22 Oct
 * 2026): each block keeps its heading, its card and its rows' height, so only
 * the numbers and names fill in. The route's loading screen draws these, and
 * so does each block while its own read is on the way.
 */

import { ActionList, ActionRow, Skeleton, SkeletonRow } from "../ui/kit";
import myDay from "./my-day.module.css";
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

/** A salesperson's Today and their day's numbers. */
export function TodaySkeleton() {
  return (
    <>
      {/* Taking new leads: its row's icon and two lines. */}
      <section className={styles.taking} aria-hidden="true">
        <SkeletonRow avatar={40} lines={2} />
      </section>
      <section className={styles.block} aria-busy="true">
        <div className={styles.head}>
          <h2>Today</h2>
          <span className={styles.meta}>Who to call</span>
        </div>
        <div className={styles.chips} aria-hidden="true">
          {[64, 112, 104].map((width) => (
            <Skeleton key={width} width={width} height={44} radius="pill" />
          ))}
        </div>
        <RowsSkeleton rows={4} kind="lead" />
        <Skeleton height={52} radius="pill" />
        {/* "See all N for today" */}
        <span className={`${styles.more} ${styles.line}`} aria-hidden="true">
          <Skeleton width={136} height={12} />
        </span>
      </section>
      <section className={myDay.numbers} aria-hidden="true">
        <h3 className={myDay.numbersTitle}>Today</h3>
        <dl className={styles.dayStrip}>
          {["Calls", "Connected", "Follow-ups done"].map((label) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className={styles.line}>
                <Skeleton width={28} height={18} />
              </dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}

/** The whole Home in an organisation, for the route's loading screen. */
export function SalesHomeSkeleton({ manager }: { manager: boolean }) {
  return (
    <div className={styles.home} aria-busy="true" aria-label="Loading Home">
      {manager ? (
        <>
          {/* Team | My day */}
          <Skeleton height={46} radius="pill" />
          <section className={styles.block}>
            <div className={styles.head}>
              <h2>How sales are going</h2>
              {/* The period chip */}
              <Skeleton width={101} height={38} radius="pill" />
            </div>
            <OutcomesSkeleton />
            {/* "N for you to call today" */}
            <div className={styles.chips} aria-hidden="true">
              <Skeleton width={190} height={44} radius="pill" />
            </div>
          </section>
          <section className={styles.block}>
            <div className={styles.head}>
              <h2>Needs you</h2>
            </div>
            <NeedsSkeleton />
          </section>
          <section className={styles.block}>
            <div className={styles.head}>
              <h2>Sellers</h2>
              <span className={styles.meta}>By what they won</span>
            </div>
            <RowsSkeleton rows={3} kind="seller" />
          </section>
          <section className={styles.block}>
            <div className={styles.head}>
              <h2>Open leads by stage</h2>
            </div>
            <FunnelSkeleton />
          </section>
        </>
      ) : (
        <TodaySkeleton />
      )}
    </div>
  );
}
