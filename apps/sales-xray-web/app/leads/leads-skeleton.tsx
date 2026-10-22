/**
 * The Leads screen's outline while it opens, light enough for the app's root
 * loading screen (design system v2, 20 Oct): only the kit, styles and the
 * shell, never the Lead Desk page or its API client.
 *
 * It is the final layout of the default view, To call (Liquid Glass polish,
 * 22 Oct 2026: nothing moves when the page arrives): the one header row (Taking
 * leads, the ⋯ menu), the stage tabs, then the Today card with its rows. On a
 * computer the page head and tiles stand above, as they do once loaded.
 */

import { AcquisitionShell } from "../acquisition-shell";
import { Panel, Skeleton, SkeletonRow } from "../ui/kit";
import styles from "./leads.module.css";

/** The stage tabs' widths as they read at 390 px: To call, Open, the first stages. */
const TABS = [109, 96, 112, 120, 104];

export function LeadsSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="leads">
      <div
        className={styles.root}
        data-tab="desk"
        aria-busy="true"
        aria-label="Loading leads"
      >
        <div className={styles.wideOnly}>
          <div className={styles.headSkeleton}>
            <Skeleton width={120} height={22} />
            <Skeleton width={260} height={12} />
          </div>
          <div className={styles.tilesSkeleton}>
            {[0, 1, 2, 3].map((key) => (
              <Skeleton key={key} height={86} />
            ))}
          </div>
        </div>
        <div className={styles.toolbar} aria-hidden="true">
          <Skeleton width={128} height={34} radius="pill" />
          <span className={styles.toolbarEnd}>
            <Skeleton width={40} height={40} radius="circle" />
          </span>
        </div>
        <div
          className={`${styles.stageTabs} ${styles.stageTabsSkeleton}`}
          aria-hidden="true"
        >
          {TABS.map((width) => (
            <Skeleton key={width} width={width} height={36} radius="pill" />
          ))}
        </div>
        <div className={styles.deskGrid}>
          <div className={styles.deskMain}>
            <Panel title="Today">
              {/* The first section's title (Overdue, Call now) and its count. */}
              <h3 className={styles.sectionTitle} aria-hidden="true">
                <Skeleton width={64} height={12} />
                <Skeleton width={22} height={20} radius="pill" />
              </h3>
              <div className={styles.leadRowsSkeleton}>
                {[0, 1, 2, 3, 4].map((key) => (
                  <SkeletonRow key={key} avatar={40} lines={3} />
                ))}
              </div>
            </Panel>
          </div>
        </div>
      </div>
    </AcquisitionShell>
  );
}
