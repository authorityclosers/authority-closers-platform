/**
 * The Leads screen's outline while it opens, light enough for the app's root
 * loading screen (design system v2, 20 Oct): only the kit, styles and the
 * shell, never the Lead Desk page or its API client.
 */

import { AcquisitionShell } from "../acquisition-shell";
import { Skeleton } from "../ui/kit";
import styles from "./leads.module.css";

export function LeadsSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="leads">
      <div className={styles.root} aria-busy="true" aria-label="Loading leads">
        <div className={styles.headSkeleton}>
          <Skeleton width={120} height={22} />
          <Skeleton width={260} height={12} />
        </div>
        <div className={styles.tilesSkeleton}>
          {[0, 1, 2, 3].map((key) => (
            <Skeleton key={key} height={86} />
          ))}
        </div>
        <Skeleton height={320} />
      </div>
    </AcquisitionShell>
  );
}
