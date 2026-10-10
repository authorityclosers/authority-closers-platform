"use client";

import styles from "./organisation.module.css";

/** Team calls the Overview lists before "Show all". */
export const CALLS_SHOWN = 8;

/**
 * The Organisation page while it loads: its own header, tabs and Overview
 * surfaces with placeholder lines, so nothing moves when the data arrives.
 * Light on purpose: the session check draws it before the page's code loads.
 */
export function OrganisationPageSkeleton() {
  return (
    <div className={styles.page} data-organisation-view>
      <OrganisationSkeleton />
    </div>
  );
}

export function OrganisationSkeleton() {
  return (
    <div
      className={styles.skeleton}
      role="status"
      aria-busy="true"
      aria-label="Loading organisation"
    >
      <div className={styles.skeletonHeader}>
        <span className={styles.skeletonTile} />
        <span className={styles.skeletonLines}>
          <i />
          <i />
        </span>
      </div>
      <div className={styles.tabs} aria-hidden="true">
        {Array.from({ length: 3 }, (_, index) => (
          <span key={index} className={styles.tab}>
            <i className={styles.bone} data-w="tab" />
          </span>
        ))}
      </div>
      <SkeletonBlocks />
    </div>
  );
}

/** The loaded Overview's own surfaces with placeholder lines, so nothing jumps. */
export function SkeletonBlocks({ team = true }: { team?: boolean }) {
  const lines = (count: number) =>
    Array.from({ length: count }, (_, index) => (
      <span key={index} className={styles.boneRow}>
        <i className={styles.bone} data-w="name" />
        <i className={styles.bone} data-w="meta" />
      </span>
    ));
  // Each block keeps its heading row, as the loaded sections do.
  const head = (
    <div className={styles.sectionHead}>
      <i className={styles.bone} data-w="head" />
    </div>
  );
  return (
    <div className={styles.overview}>
      <div className={styles.section} aria-hidden="true">
        {head}
        <div className={styles.strip} data-columns={team ? 4 : 3}>
          {Array.from({ length: team ? 4 : 3 }, (_, index) => (
            <span key={index} className={styles.kpi}>
              <i className={styles.bone} data-w="label" />
              <i className={styles.bone} data-w="value" />
              <i className={styles.bone} data-w="context" />
            </span>
          ))}
        </div>
      </div>
      <div
        className={styles.columns}
        data-team={team ? "" : undefined}
        aria-hidden="true"
      >
        <div className={styles.section}>
          {head}
          <div className={styles.surface}>{lines(CALLS_SHOWN)}</div>
        </div>
        {team ? (
          <div className={styles.section}>
            {head}
            <div className={styles.surface}>{lines(4)}</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
