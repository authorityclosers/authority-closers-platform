"use client";

/**
 * Settings while the session is checked: the same frame, side list and
 * section title the page draws, with placeholder panels where the section's
 * own panes arrive, so nothing moves when they do (owner, 20 Oct). The
 * overview needs no data, so it shows as it is.
 */
import { usePathname } from "next/navigation";

import { Skeleton } from "../ui/kit";
import {
  SettingsOverview,
  SettingsShell,
  currentSection,
} from "./settings-shell";
import styles from "./settings-shell.module.css";

// Rows in each placeholder panel.
const PANELS = [3, 2] as const;

export function SettingsSkeleton() {
  const section = currentSection(usePathname());
  return (
    <SettingsShell>
      <div
        className={styles.loading}
        role="status"
        aria-busy="true"
        aria-label="Loading settings"
      >
        {section === null ? (
          <SettingsOverview />
        ) : (
          PANELS.map((rows, panel) => (
            <div
              key={panel}
              className={styles.skeletonPanel}
              aria-hidden="true"
            >
              <span className={styles.skeletonHead}>
                <Skeleton width="34%" height={12} />
              </span>
              {Array.from({ length: rows }, (_, row) => (
                <span key={row} className={styles.skeletonRow}>
                  <Skeleton width={36} height={36} />
                  <span className={styles.skeletonLines}>
                    <Skeleton width="46%" height={12} />
                    <Skeleton width="72%" height={10} />
                  </span>
                </span>
              ))}
            </div>
          ))
        )}
      </div>
    </SettingsShell>
  );
}
