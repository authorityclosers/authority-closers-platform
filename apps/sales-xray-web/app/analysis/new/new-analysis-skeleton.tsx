"use client";

import { AcquisitionFileStage } from "../../acquisition-file-stage";
import { AcquisitionShell } from "../../acquisition-shell";
import styles from "../../acquisition-studio.module.css";
import { useTheme } from "../../lightbox/theme-provider";
import { NewAnalysisFooter, NewAnalysisHero } from "../../new-analysis-hero";
import { useWorkspaceAccess } from "../../workspace-access";

/** The studio's first allowance line, before its reads answer (tested). */
export const CHECKING_ALLOWANCE = "Remaining analysis time · checking…";

const ignore = () => {};

/**
 * New analysis while its route or session loads: the studio's own upload
 * screen (heading, drop area, footer) in its wrappers, with the file picker
 * held until the page is ready. The loaded page draws the same boxes, so
 * the only change on arrival is that "Choose a file" wakes up.
 */
export function NewAnalysisSkeletonContent() {
  const theme = useTheme()?.resolved ?? "light";
  return (
    <div
      className={`xray-app simple-app ${styles.app}`}
      data-theme={theme}
      data-variant="standalone"
      data-stage="upload"
      data-selected="false"
      role="status"
      aria-busy="true"
      aria-label="Loading New analysis"
    >
      <div className="studio-main">
        <div className={`${styles.layout} ${styles.quietIntake}`}>
          <div className={styles.primaryColumn}>
            <NewAnalysisHero />
            <section
              className={`panel studio-upload ${styles.upload}`}
              aria-hidden="true"
            >
              <AcquisitionFileStage
                files={[]}
                selectedFile={null}
                onSelect={ignore}
                onRemove={ignore}
                onClear={ignore}
                onAddFiles={ignore}
                disabled
              />
            </section>
            <NewAnalysisFooter allowanceLabel={CHECKING_ALLOWANCE} />
          </div>
        </div>
      </div>
    </div>
  );
}

/** The route's loading screen: the shell as the studio sets it, then the above. */
export function NewAnalysisSkeleton() {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
      active="analyse"
      heroStage="welcome"
      mobileFit
    >
      <NewAnalysisSkeletonContent />
    </AcquisitionShell>
  );
}
