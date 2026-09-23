"use client";

import Link from "next/link";
import { AcquisitionGuideRail } from "./acquisition-dashboard-panels";
import { AcquisitionProcessingPanel } from "./acquisition-processing-panel";
import { AcquisitionShell } from "./acquisition-shell";
import { projectProcessing } from "./processing-state";
import type { FixtureReviewFrame } from "./fixture-review-states";
import styles from "./acquisition-studio.module.css";

/** The development review port alone may supply this synthetic frame. */
export function SalesXrayFixturePreview({
  frame,
  message,
}: {
  frame: FixtureReviewFrame | null;
  message: string;
}) {
  if (!frame || frame.kind !== "processing" || !frame.progress) {
    return (
      <AcquisitionShell authenticated={false}>
        <section className="panel" role="status" aria-live="polite">
          <h1>Opening local test state</h1>
          <p>{message || "Checking local review availability…"}</p>
          <Link href="/__review/">Review controls</Link>
        </section>
      </AcquisitionShell>
    );
  }

  const projection = projectProcessing(frame.progress, false);
  return (
    <AcquisitionShell
      authenticated={false}
      mobileFit
      heroStage="processing"
      previewHero
    >
      <div
        className={`xray-app simple-app ${styles.app}`}
        data-theme="light"
        data-variant="standalone"
        data-stage="processing"
        data-fixture="true"
      >
        <div className="studio-main">
          <nav className={styles.reviewNotice} aria-label="Fixture state navigation">
            <div>
              <strong>{frame.label}</strong>
              <small>
                Local test state {frame.navigation.position} of {frame.navigation.total}.
                Synthetic display only; no call or report exists.
              </small>
            </div>
            <div className={styles.reviewNavigationLinks}>
              {frame.navigation.previousUrl ? (
                <Link href={frame.navigation.previousUrl}>Previous state</Link>
              ) : (
                <span aria-disabled="true">Previous state</span>
              )}
              {frame.navigation.nextUrl ? (
                <Link href={frame.navigation.nextUrl}>Next state</Link>
              ) : (
                <span aria-disabled="true">Next state</span>
              )}
              <Link href="/__review/">All states</Link>
            </div>
          </nav>
          <div className={styles.layout}>
            <div className={styles.primaryColumn}>
              <AcquisitionProcessingPanel
                staticPreview
                stageRows={projection.rows}
                statusText={projection.title}
                progress={frame.progress}
                paused={projection.attention}
                fileName="Example call.wav"
                fileMeta="Synthetic audio · no file stored"
              />
            </div>
            <AcquisitionGuideRail stage="empty" />
          </div>
        </div>
      </div>
    </AcquisitionShell>
  );
}
