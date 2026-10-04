"use client";

import { useRef, useState } from "react";

import type { Allowance } from "../../acquisition-client";
import { AcquisitionShell } from "../../acquisition-shell";
import { CallAudioDock } from "../../call-audio-dock";
import { CallContext } from "../../call-context";
import { CallMap, CallMapMini } from "../../call-map";
import { CallSignals } from "../../call-signals";
import { DipakOverview, ReportAnalysis } from "../../dipak-overview";
import { ReportCoaching } from "../../report-coaching";
import { UploadSessionProvider } from "../../hooks/upload-session";
import { KeyFacts } from "../../key-facts";
import { useTheme } from "../../lightbox/theme-provider";
import { ProspectSnapshot } from "../../prospect-snapshot";
import type { ReportEvidence } from "../../report-contract";
import { ReportHeader } from "../../report-header";
import { ReportModes } from "../../report-modes";
import { ReportMoments } from "../../report-moments";
import { ReportRawData } from "../../report-raw-data";
import { ReportScrollRail } from "../../report-scroll-rail";
import {
  ReportTranscript,
  formatTranscriptTime,
} from "../../report-transcript";
import { TranscriptReader } from "../../transcript-reader";
import { SalesSkills } from "../../sales-skills";
import { SourceWaveformProvider } from "../../source-waveform";
import { WorkspaceAccessProvider } from "../../workspace-access";
import { syntheticReport } from "../report/synthetic-report";
import baseFixture from "../../../tests/fixtures/dipak-overview.json";
import acquisitionStyles from "../../acquisition-studio.module.css";
import styles from "./full-shell-preview.module.css";

/** Fictional identity: never a real person, session or workspace. */
const FIXTURE_ACCESS = {
  status: "ready" as const,
  authenticated: true,
  context: {
    personId: "fixture-person",
    sessionId: "fixture-session",
    tenantId: "fixture-workspace",
  },
  retry: () => {},
};

/** Fictional allowance so the shell meter renders; not a real balance. */
const FIXTURE_ALLOWANCE: Allowance = {
  allowance_seconds: 3_600,
  committed_seconds: 1_080,
  available_seconds: 2_520,
};

const FIXTURE_DURATION_MS = 3_598_000;

/** A fictional call id: local notes (speaker names, facts, ticks) stay in this browser only. */
const FIXTURE_CALL_ID = "00000000-0000-4000-8000-000000000002";

/**
 * The actual Sales Xray shell, report header, report sections and call dock
 * mounted with invented data for local visual review. The section list and
 * the props mirror the live report in acquisition-studio.tsx; keep them in
 * step when a section is added there. No recording, account, analysis or
 * provider call exists; actions only report what they would do.
 */
export function FullShellPreview() {
  const audio = useRef<HTMLAudioElement>(null);
  // Like the live studio: a light report sheet unless the app is dark.
  const resolvedTheme = useTheme()?.resolved ?? "light";
  const [status, setStatus] = useState(
    "Fictional fixture. Actions here do not reach any service.",
  );
  const [transcriptReaderOpen, setTranscriptReaderOpen] = useState(false);
  const transcript = {
    ...baseFixture.transcript,
    duration_ms: FIXTURE_DURATION_MS,
  };
  const selectSource = (evidence: ReportEvidence, title: string) =>
    setStatus(
      `Selected ${formatTranscriptTime(evidence.start_ms)}–${formatTranscriptTime(evidence.end_ms)} · ${title}. No audio exists in this fixture.`,
    );
  const seek = (evidence: ReportEvidence) =>
    selectSource(evidence, "Report moment");
  const playFrom = (ms: number) =>
    setStatus(
      `Would play from ${formatTranscriptTime(ms)}. No audio exists in this fixture.`,
    );
  const unlock = () =>
    setStatus("Would open the sign-in page. Nothing was sent.");

  return (
    <UploadSessionProvider>
      <WorkspaceAccessProvider value={FIXTURE_ACCESS}>
        <AcquisitionShell
          authenticated
          homeHref="/review-fixture/shell"
          active="analyse"
          mobileFit
          allowance={FIXTURE_ALLOWANCE}
        >
          {/* Production's report ancestry: shell main > .xray-app > .studio-main,
              the report's own scroll container under the mobile-fit shell. */}
          <div
            className={`xray-app simple-app ${acquisitionStyles.app} ${styles.page}`}
            data-theme={resolvedTheme}
            data-variant="standalone"
            data-stage="report"
            data-full-shell-fixture="true"
          >
            <div className="studio-main">
              <p className={styles.banner} role="note">
                Development fixture · fictional data · no account, recording or
                provider call
              </p>
              <SourceWaveformProvider audioRef={audio}>
                <section
                  className={`studio-report panel ${acquisitionStyles.report} ${styles.report}`}
                  aria-label="Sales call report"
                  data-lx-surface={
                    resolvedTheme === "dark" ? undefined : "light"
                  }
                >
                  <ReportHeader
                    durationMs={FIXTURE_DURATION_MS}
                    languageLabel="Marathi + English"
                    sourceLabel="Fictional fixture transcript"
                    claimed
                    busy={false}
                    canDownload={false}
                    canRequestDeletion
                    deletionDisabled
                    onOpenTranscript={() => setTranscriptReaderOpen(true)}
                    onAnalyseAnother={() =>
                      setStatus("Would open New analysis. Nothing was sent.")
                    }
                    visual={
                      <CallMap
                        callId={FIXTURE_CALL_ID}
                        transcript={transcript}
                        report={syntheticReport}
                        durationMs={FIXTURE_DURATION_MS}
                        onSelectEvidence={seek}
                        onSeek={playFrom}
                      />
                    }
                    context={
                      <CallContext
                        callId={FIXTURE_CALL_ID}
                        report={syntheticReport}
                        transcript={transcript}
                      />
                    }
                    compactVisual={
                      <CallMapMini
                        report={syntheticReport}
                        durationMs={FIXTURE_DURATION_MS}
                        onSeek={playFrom}
                      />
                    }
                    onDownload={() => {}}
                    onRequestDeletion={() => {}}
                  />
                  <ReportModes
                    documentData={{
                      report: syntheticReport,
                      transcript,
                      title: "Fictional sample call",
                    }}
                    label="Explore your sales report"
                    lightSurface={resolvedTheme !== "dark"}
                    boundCallId={FIXTURE_CALL_ID}
                    panels={[
                      {
                        id: "overview",
                        label: "Overview",
                        content: (
                          <DipakOverview
                            showHeading={false}
                            report={syntheticReport}
                            transcript={transcript}
                            callId={FIXTURE_CALL_ID}
                            durationMs={FIXTURE_DURATION_MS}
                            onSelectEvidence={seek}
                            onSelectContextualPlayback={(_selection, title) =>
                              setStatus(
                                `Would play with context · ${title}. No audio exists in this fixture.`,
                              )
                            }
                            onUnlock={unlock}
                          />
                        ),
                      },
                      {
                        id: "transcript",
                        label: "Transcript",
                        content: (
                          <ReportTranscript
                            transcript={transcript}
                            callId={FIXTURE_CALL_ID}
                            language="en"
                            onSelect={(segment) =>
                              selectSource(
                                {
                                  segment_id: segment.id,
                                  quote: segment.text,
                                  start_ms: segment.start_ms,
                                  end_ms: segment.end_ms,
                                },
                                "Transcript excerpt",
                              )
                            }
                          />
                        ),
                      },
                      {
                        id: "moments",
                        label: "Moments",
                        content: (
                          <ReportMoments
                            report={syntheticReport}
                            callId={FIXTURE_CALL_ID}
                            transcript={transcript}
                            onSelectEvidence={seek}
                            onSelectContextualPlayback={(_selection, title) =>
                              setStatus(
                                `Would play with context · ${title}. No audio exists in this fixture.`,
                              )
                            }
                            onUnlock={unlock}
                          />
                        ),
                      },
                      {
                        id: "analysis",
                        label: "Analysis",
                        content: (
                          <>
                            <ReportAnalysis
                              showHeading={false}
                              report={syntheticReport}
                              transcript={transcript}
                              callId={FIXTURE_CALL_ID}
                              durationMs={FIXTURE_DURATION_MS}
                              onSelectEvidence={seek}
                              onSelectContextualPlayback={(_selection, title) =>
                                setStatus(
                                  `Would play with context · ${title}. No audio exists in this fixture.`,
                                )
                              }
                              onUnlock={unlock}
                              onSeek={playFrom}
                            />
                            <SalesSkills
                              dimensions={syntheticReport.dimensions}
                              callId={FIXTURE_CALL_ID}
                              transcript={transcript}
                              onSelectEvidence={seek}
                            />
                            <KeyFacts
                              callId={FIXTURE_CALL_ID}
                              transcript={transcript}
                              report={syntheticReport}
                              durationMs={FIXTURE_DURATION_MS}
                              onSeek={playFrom}
                            />
                            <ProspectSnapshot
                              report={syntheticReport}
                              callId={FIXTURE_CALL_ID}
                              transcript={transcript}
                              onSelectEvidence={seek}
                              onUnlock={unlock}
                            />
                            <CallSignals
                              callId={FIXTURE_CALL_ID}
                              transcript={transcript}
                              onSeek={playFrom}
                            />
                            <ReportRawData
                              callId={FIXTURE_CALL_ID}
                              transcript={transcript}
                              report={syntheticReport}
                              durationMs={FIXTURE_DURATION_MS}
                              runId={null}
                              onSeek={playFrom}
                            />
                          </>
                        ),
                      },
                      {
                        id: "coaching",
                        label: "Coaching",
                        content: (
                          <ReportCoaching
                            report={syntheticReport}
                            transcript={transcript}
                            callId={FIXTURE_CALL_ID}
                            durationMs={FIXTURE_DURATION_MS}
                            onSelectEvidence={seek}
                            onUnlock={unlock}
                          />
                        ),
                      },
                    ]}
                  />
                  <ReportScrollRail />
                  <TranscriptReader
                    isOpen={transcriptReaderOpen}
                    onClose={() => setTranscriptReaderOpen(false)}
                    transcript={transcript}
                    report={syntheticReport}
                    callId={FIXTURE_CALL_ID}
                    callTitle="Fictional seller — sample call report"
                    onSeek={playFrom}
                    audioAvailable
                  />
                  <p
                    className={styles.status}
                    role="status"
                    aria-label="Fixture action status"
                    aria-live="polite"
                  >
                    {status}
                  </p>
                </section>
                <CallAudioDock
                  audioRef={audio}
                  src=""
                  durationMs={FIXTURE_DURATION_MS}
                  title="Fictional fixture · no audio"
                />
              </SourceWaveformProvider>
            </div>
          </div>
        </AcquisitionShell>
      </WorkspaceAccessProvider>
    </UploadSessionProvider>
  );
}
