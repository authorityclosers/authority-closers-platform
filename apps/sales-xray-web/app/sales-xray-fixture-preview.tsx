"use client";

import { AudioLines, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { AccountAuth } from "./account-auth";
import { AcquisitionGuideRail } from "./acquisition-dashboard-panels";
import { AcquisitionFileStage } from "./acquisition-file-stage";
import { AcquisitionProcessingPanel } from "./acquisition-processing-panel";
import { AcquisitionShell } from "./acquisition-shell";
import { projectProcessing } from "./processing-state";
import type { FixtureReviewFrame } from "./fixture-review-states";
import styles from "./acquisition-studio.module.css";
import previewStyles from "./sales-xray-fixture-preview.module.css";

const MAX_PREVIEW_BYTES = 32 * 1048576;

function syntheticFiles() {
  return [
    new File([new Uint8Array(512 * 1024)], "Synthetic discovery call.wav", {
      type: "audio/wav",
    }),
    new File([new Uint8Array(768 * 1024)], "Synthetic objection call.mp3", {
      type: "audio/mpeg",
    }),
    new File([new Uint8Array(640 * 1024)], "Synthetic follow-up call.m4a", {
      type: "audio/mp4",
    }),
  ] as const;
}

/** Browser-only, local File objects. No input, upload, or provider operation. */
function SelectedFilePreview({ label }: { label: string }) {
  const [files] = useState(syntheticFiles);
  const [mode, setMode] = useState<"single" | "multiple">("single");
  const visibleFiles = mode === "single" ? files.slice(0, 1) : files;

  return (
    <AcquisitionShell authenticated={false} mobileFit welcome>
      <div
        className={`xray-app simple-app ${styles.app} ${previewStyles.selectedApp}`}
        data-theme="light"
        data-variant="standalone"
        data-stage="upload"
        data-selected="true"
        data-fixture="true"
        data-preview-mode={mode}
      >
        <div className="studio-main">
          <nav
            className={`${styles.reviewNotice} ${previewStyles.navigation}`}
            aria-label="Synthetic file preview controls"
          >
            <div>
              <strong>{label} · Synthetic layout preview</strong>
              <small>No real recording is selected, stored, or uploaded.</small>
            </div>
            <div className={previewStyles.modeSwitch} role="group" aria-label="Number of preview files">
              <button type="button" aria-pressed={mode === "single"} onClick={() => setMode("single")}>1 file</button>
              <button type="button" aria-pressed={mode === "multiple"} onClick={() => setMode("multiple")}>3 files</button>
              <a href="/__review/">All states</a>
            </div>
          </nav>
          <div className={styles.layout}>
            <div className={styles.primaryColumn}>
              <section className={`panel studio-upload ${styles.upload} ${previewStyles.selectedCard}`} aria-label="Your call">
                <div className={styles.uploadCardHeader}>
                  <div className={styles.uploadCardTitle}>
                    <AudioLines size={35} aria-hidden="true" />
                    <h2>Add a call to review</h2>
                  </div>
                  <span className={styles.allowanceBadge}>
                    <ShieldCheck size={18} aria-hidden="true" /> Preview only
                  </span>
                </div>
                <div
                  onClickCapture={(event) => {
                    // Keep production controls visually exact while preventing
                    // the fixture from opening a real browser file picker.
                    if ((event.target as Element).closest("button")) {
                      event.preventDefault();
                      event.stopPropagation();
                    }
                  }}
                >
                  <AcquisitionFileStage
                    files={visibleFiles}
                    selectedFile={visibleFiles[0]}
                    onSelect={() => {}}
                    onRemove={() => {}}
                    onClear={() => {}}
                    onAddFiles={() => {}}
                    maxBytes={MAX_PREVIEW_BYTES}
                    maxMinutes={60}
                    disabled={false}
                  />
                </div>
              </section>
            </div>
            <AcquisitionGuideRail
              stage="selected"
              stagedFiles={visibleFiles}
              maximumFileBytes={MAX_PREVIEW_BYTES}
              staticPreview
            />
          </div>
        </div>
      </div>
    </AcquisitionShell>
  );
}

/** The development review port alone may supply this synthetic frame. */
export function SalesXrayFixturePreview({
  frame,
  message,
}: {
  frame: FixtureReviewFrame | null;
  message: string;
}) {
  if (
    frame?.id === "auth.email" ||
    frame?.id === "auth.code" ||
    frame?.id === "auth.error"
  )
    return (
      <div className={previewStyles.authFixture} data-fixture="true">
        <span className={previewStyles.authFixtureLabel}>
          Synthetic sign-in preview · No account request is sent
        </span>
        <AccountAuth
          selectedFile={{ name: "Synthetic selected call.wav", size: 524288 }}
          previewState={frame.id}
          onAuthenticated={() => {}}
          onCancel={() => {}}
        />
      </div>
    );
  if (frame?.id === "upload.selected")
    return <SelectedFilePreview label={frame.label} />;
  if (!frame || frame.kind !== "processing" || !frame.progress) {
    return (
      <AcquisitionShell authenticated={false}>
        <section className="panel" role="status" aria-live="polite">
          <h1>Opening local test state</h1>
          <p>{message || "Checking local review availability…"}</p>
          <a href="/__review/">Review controls</a>
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
        className={`xray-app simple-app ${styles.app} ${previewStyles.processingApp}`}
        data-theme="light"
        data-variant="standalone"
        data-stage="processing"
        data-fixture="true"
      >
        <div className="studio-main">
          <nav className={`${styles.reviewNotice} ${previewStyles.navigation}`} aria-label="Fixture state navigation">
            <div>
              <strong>{frame.label}</strong>
              <small>
                Local test state {frame.navigation.position} of {frame.navigation.total}.
                Synthetic display only; no call or report exists.
              </small>
            </div>
            <div className={styles.reviewNavigationLinks}>
              {frame.navigation.previousUrl ? (
                <a href={frame.navigation.previousUrl}>Previous state</a>
              ) : (
                <span aria-disabled="true">Previous state</span>
              )}
              {frame.navigation.nextUrl ? (
                <a href={frame.navigation.nextUrl}>Next state</a>
              ) : (
                <span aria-disabled="true">Next state</span>
              )}
              <a href="/__review/">All states</a>
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
          </div>
        </div>
      </div>
    </AcquisitionShell>
  );
}
