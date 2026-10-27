"use client";

import Link from "next/link";
import { useRef, useState, type ReactNode } from "react";

import type { Allowance } from "../../acquisition-client";
import { AcquisitionShell } from "../../acquisition-shell";
import { CallAudioDock } from "../../call-audio-dock";
import { CallContext } from "../../call-context";
import { CallMap, CallMapMini } from "../../call-map";
import { CallSignals } from "../../call-signals";
import { KeyFacts } from "../../key-facts";
import { useTheme } from "../../lightbox/theme-provider";
import { NextCallPlan } from "../../next-call-plan";
import { OverviewHook } from "../../overview-hook";
import { ProspectSnapshot } from "../../prospect-snapshot";
import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "../../report-contract";
import { ReportHeader } from "../../report-header";
import { ReportModes } from "../../report-modes";
import { ReportMoments } from "../../report-moments";
import { ReportRawData } from "../../report-raw-data";
import { ReportScrollRail } from "../../report-scroll-rail";
import {
  ReportTranscript,
  formatTranscriptTime,
} from "../../report-transcript";
import { SalesSkills } from "../../sales-skills";
import { SourceWaveformProvider } from "../../source-waveform";
import { TranscriptReader } from "../../transcript-reader";
import acquisitionStyles from "../../acquisition-studio.module.css";
import styles from "./sample-report-view.module.css";

export type SampleReportData = Readonly<{
  /** A fictional call's id: local notes (speaker names, ticks) stay in this browser. */
  callId: string;
  report: SalesReport;
  transcript: Transcript;
  durationMs: number;
  languageLabel: string;
  sourceLabel: string;
  title: string;
  /** The recording to play, or "" for none. */
  audioSrc: string;
}>;

/**
 * The real report, mounted with a fictional call and nothing live: the same
 * header, sections and call dock as acquisition-studio.tsx (keep them in step
 * when a section is added there). Two uses:
 * - "sample" (/analysis/sample, 27 Oct 2026): a new workspace's look at what a
 *   report shows, inside the signed-in shell, with the sample call's own
 *   recording to play. No API read, no AI.
 * - "fixture" (/review-fixture/shell): local visual review; no audio, and each
 *   action only says what it would do.
 */
export function SampleReportView({
  data,
  variant,
  homeHref,
  banner,
  allowance,
}: {
  data: SampleReportData;
  variant: "sample" | "fixture";
  homeHref: string;
  banner: ReactNode;
  /** The shell's minutes meter: the fixture's fictional one; none for the sample. */
  allowance?: Allowance;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  // Like the live studio: a light report sheet unless the app is dark.
  const resolvedTheme = useTheme()?.resolved ?? "light";
  const sample = variant === "sample";
  const [status, setStatus] = useState(
    sample
      ? "A sample report of a fictional call."
      : "Fictional fixture. Actions here do not reach any service.",
  );
  const [transcriptReaderOpen, setTranscriptReaderOpen] = useState(false);
  const { callId, report, transcript, durationMs } = data;
  const playFrom = (ms: number) => {
    const player = audio.current;
    if (sample && player && data.audioSrc) {
      player.currentTime = ms / 1000;
      void player.play().catch(() => undefined);
      return;
    }
    setStatus(
      `Would play from ${formatTranscriptTime(ms)}. No audio exists in this fixture.`,
    );
  };
  const selectSource = (evidence: ReportEvidence, title: string) => {
    if (sample) {
      playFrom(evidence.start_ms);
      return;
    }
    setStatus(
      `Selected ${formatTranscriptTime(evidence.start_ms)}–${formatTranscriptTime(evidence.end_ms)} · ${title}. No audio exists in this fixture.`,
    );
  };
  const seek = (evidence: ReportEvidence) =>
    selectSource(evidence, "Report moment");
  const unlock = () =>
    setStatus(
      sample
        ? "This is a sample: its parts are all open."
        : "Would open the sign-in page. Nothing was sent.",
    );

  return (
    <AcquisitionShell
      authenticated
      pageName={sample ? "Sample report" : "Report"}
      homeHref={homeHref}
      active="analyse"
      mobileFit
      allowance={allowance}
    >
      {/* Production's report ancestry: shell main > .xray-app > .studio-main,
          the report's own scroll container under the mobile-fit shell. */}
      <div
        className={`xray-app simple-app ${acquisitionStyles.app} ${styles.page}`}
        data-theme={resolvedTheme}
        data-variant="standalone"
        data-stage="report"
        data-full-shell-fixture={sample ? undefined : "true"}
        data-sample-report={sample ? "true" : undefined}
      >
        <div className="studio-main">
          <div className={styles.banner} role="note">
            {banner}
          </div>
          <SourceWaveformProvider audioRef={audio}>
            <section
              className={`studio-report panel ${acquisitionStyles.report} ${styles.report}`}
              aria-label="Sales call report"
              data-lx-surface={resolvedTheme === "dark" ? undefined : "light"}
            >
              <ReportHeader
                durationMs={durationMs}
                languageLabel={data.languageLabel}
                sourceLabel={data.sourceLabel}
                claimed
                busy={false}
                canDownload={false}
                canRequestDeletion={!sample}
                deletionDisabled
                onOpenTranscript={() => setTranscriptReaderOpen(true)}
                onAnalyseAnother={() =>
                  setStatus(
                    sample
                      ? "Analyse your own call from + on any screen."
                      : "Would open New analysis. Nothing was sent.",
                  )
                }
                fallbackTitle={sample ? data.title : undefined}
                visual={
                  <CallMap
                    callId={callId}
                    transcript={transcript}
                    report={report}
                    durationMs={durationMs}
                    onSelectEvidence={seek}
                    onSeek={playFrom}
                  />
                }
                context={
                  <CallContext
                    callId={callId}
                    report={report}
                    transcript={transcript}
                  />
                }
                compactVisual={
                  <CallMapMini
                    report={report}
                    durationMs={durationMs}
                    onSeek={playFrom}
                  />
                }
                onDownload={() => {}}
                onRequestDeletion={() => {}}
              />
              <ReportModes
                fixture
                documentData={{ report, transcript, title: data.title }}
                label="Explore your sales report"
                lightSurface={resolvedTheme !== "dark"}
                boundCallId={callId}
                panels={[
                  {
                    id: "overview",
                    label: "Overview",
                    content: (
                      <OverviewHook
                        report={report}
                        transcript={transcript}
                        callId={callId}
                        onSeek={playFrom}
                        onUnlock={unlock}
                      />
                    ),
                  },
                  {
                    id: "moments",
                    label: "Moments",
                    content: (
                      <ReportMoments
                        report={report}
                        callId={callId}
                        transcript={transcript}
                        onSelectEvidence={seek}
                        onSelectContextualPlayback={(playback, title) =>
                          sample
                            ? playFrom(playback.evidence.start_ms)
                            : setStatus(
                                `Would play with context · ${title}. No audio exists in this fixture.`,
                              )
                        }
                        onUnlock={unlock}
                      />
                    ),
                  },
                  {
                    id: "prospect",
                    label: "Prospect",
                    content: (
                      <>
                        <KeyFacts
                          callId={null}
                          transcript={transcript}
                          report={report}
                          durationMs={durationMs}
                          onSeek={playFrom}
                        />
                        <ProspectSnapshot
                          report={report}
                          callId={callId}
                          transcript={transcript}
                          onSelectEvidence={seek}
                          onUnlock={unlock}
                        />
                      </>
                    ),
                  },
                  {
                    id: "next-call-plan",
                    label: "Next-call plan",
                    compactLabel: "Next-call",
                    content: (
                      <NextCallPlan
                        report={report}
                        callId={callId}
                        transcript={transcript}
                        onSelectEvidence={seek}
                        onUnlock={unlock}
                      />
                    ),
                  },
                  {
                    id: "skills",
                    label: "Sales skills",
                    compactLabel: "Skills",
                    content: (
                      <SalesSkills
                        dimensions={report.dimensions}
                        callId={callId}
                        transcript={transcript}
                        onSelectEvidence={seek}
                      />
                    ),
                  },
                  {
                    id: "signals",
                    label: "Call signals",
                    content: (
                      <CallSignals
                        callId={callId}
                        transcript={transcript}
                        onSeek={playFrom}
                      />
                    ),
                  },
                  {
                    id: "transcript",
                    label: "Transcript",
                    content: (
                      <ReportTranscript
                        transcript={transcript}
                        callId={callId}
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
                    id: "raw-data",
                    label: "Raw data",
                    content: (
                      <ReportRawData
                        callId={callId}
                        transcript={transcript}
                        report={report}
                        durationMs={durationMs}
                        runId={null}
                        onSeek={playFrom}
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
                report={report}
                callId={callId}
                callTitle={data.title}
                onSeek={playFrom}
                audioAvailable={sample ? Boolean(data.audioSrc) : true}
              />
              <p
                className={styles.status}
                role="status"
                aria-label={
                  sample ? "Sample report status" : "Fixture action status"
                }
                aria-live="polite"
              >
                {status}
              </p>
            </section>
            <CallAudioDock
              audioRef={audio}
              src={data.audioSrc}
              durationMs={durationMs}
              title={sample ? data.title : "Fictional fixture · no audio"}
            />
          </SourceWaveformProvider>
        </div>
      </div>
    </AcquisitionShell>
  );
}

/** The sample's banner: what this is, and the one way to a report of your own. */
export function SampleBanner() {
  return (
    <>
      <span>
        <strong>Sample report.</strong> A fictional call, so you can see what
        Sales X-Ray finds in yours.
      </span>
      <Link href="/leads#add=lead">Add your first lead</Link>
    </>
  );
}
