"use client";

import { useRef, useState } from "react";

import type { Allowance } from "../../../acquisition-client";
import { AcquisitionShell } from "../../../acquisition-shell";
import { CallAudioDock } from "../../../call-audio-dock";
import { CallContext } from "../../../call-context";
import { CallMap, CallMapMini } from "../../../call-map";
import { CallSignals } from "../../../call-signals";
import { UploadSessionProvider } from "../../../hooks/upload-session";
import { KeyFacts } from "../../../key-facts";
import { useTheme } from "../../../lightbox/theme-provider";
import { NextCallPlan } from "../../../next-call-plan";
import { OverviewHook } from "../../../overview-hook";
import { ProspectSnapshot } from "../../../prospect-snapshot";
import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "../../../report-contract";
import { ReportHeader } from "../../../report-header";
import { ReportModes } from "../../../report-modes";
import { ReportMoments } from "../../../report-moments";
import { ReportRawData } from "../../../report-raw-data";
import { ReportScrollRail } from "../../../report-scroll-rail";
import {
  ReportTranscript,
  formatTranscriptTime,
} from "../../../report-transcript";
import { TranscriptReader } from "../../../transcript-reader";
import { SalesSkills } from "../../../sales-skills";
import { SourceWaveformProvider } from "../../../source-waveform";
import { WorkspaceAccessProvider } from "../../../workspace-access";
import { SpeakerProfilesContext } from "../../../speaker-profiles";
import { AMIT_SPEAKERS, amitReport, amitTranscript } from "./amit-call";
import { AMIT_PILLARS } from "./amit-pillars";
import { exampleView } from "../../../xray-report/example";
import { AMIT_STRUCTURE } from "./amit-structure";
import { AMIT_BRAIN4 } from "./amit-brain4";
import {
  ReportLookContext,
  VERSION_1_LOOK,
  type ReportLook,
} from "../../../report-settings";
import type { OutcomeKind } from "../../../xray-report/model";
import acquisitionStyles from "../../../acquisition-studio.module.css";
import styles from "../../shell/full-shell-preview.module.css";

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

/** A fictional call id: local notes (speaker names, facts, ticks) stay in this browser only. */
const FIXTURE_CALL_ID = "00000000-0000-4000-8000-000000000077";

export type StoryFixture = {
  report: SalesReport;
  transcript: Transcript;
  title: string;
  language: string;
  /** Names and roles as a person would confirm them; null leaves them unset. */
  speakers: {
    seller: string;
    sellerName: string;
    prospect: string;
    prospectName: string;
  } | null;
};

export const AMIT_FIXTURE: StoryFixture = {
  // Dipak's own example words, as the analysis would supply them.
  report: { ...amitReport, pillars: AMIT_PILLARS },
  transcript: amitTranscript,
  title: "Amit Sharma · discovery call",
  language: "English",
  speakers: {
    seller: AMIT_SPEAKERS.seller,
    sellerName: "Arjun",
    prospect: AMIT_SPEAKERS.prospect,
    prospectName: "Amit Sharma",
  },
};

function speakerProfiles(speakers: StoryFixture["speakers"]) {
  return {
    callId: FIXTURE_CALL_ID,
    profiles: speakers
      ? {
          [speakers.seller]: {
            name: speakers.sellerName,
            role: "you" as const,
            icon: null,
          },
          [speakers.prospect]: {
            name: speakers.prospectName,
            role: "prospect" as const,
            icon: null,
          },
        }
      : {},
    drafts: {},
    save: () => false,
    canSave: false,
    error: null,
    server: true,
  };
}

/**
 * The real Report inside the real shell, filled with the spec's own fictional
 * example call (Amit Sharma, 25:08) so every pillar has content on dev. The section list and
 * the props mirror the live report in acquisition-studio.tsx; keep them in
 * step when a section is added there. No recording, account, analysis or
 * provider call exists; actions only report what they would do.
 */
// Report settings scoring "brain4_beta": the AI coaching score is the Analysis.
const COACH_LOOK: ReportLook = { ...VERSION_1_LOOK, scoring: "brain4_beta" };

export function StoryShellPreview({
  fixture = AMIT_FIXTURE,
  example = null,
  apiStructure = false,
  coach = false,
  clean = false,
}: {
  fixture?: StoryFixture;
  /** For tutorial recordings: no development labels (the call stays fictional). */
  clean?: boolean;
  /** The call as the API sends it once an AI pointer review is saved. */
  apiStructure?: boolean;
  /** The same call with a fictional Brain 4.0 read, scored by Brain 4.0 (AI coaching score). */
  coach?: boolean;
  /** The 15 Oct doc's illustrative example and its outcome scenario. */
  example?: OutcomeKind | null;
}) {
  const title = example ? "Siddhant Pawar · discovery call" : fixture.title;
  const amitReport = coach
    ? {
        ...fixture.report,
        structure: { ...AMIT_STRUCTURE, brain4: AMIT_BRAIN4 },
      }
    : apiStructure
      ? { ...fixture.report, structure: AMIT_STRUCTURE }
      : fixture.report;
  const FIXTURE_DURATION_MS = fixture.transcript.duration_ms;
  const audio = useRef<HTMLAudioElement>(null);
  // Like the live studio: a light report sheet unless the app is dark.
  const resolvedTheme = useTheme()?.resolved ?? "light";
  const [status, setStatus] = useState(
    "Fictional fixture. Actions here do not reach any service.",
  );
  const [transcriptReaderOpen, setTranscriptReaderOpen] = useState(false);
  const transcript = fixture.transcript;
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
    <ReportLookContext.Provider value={coach ? COACH_LOOK : VERSION_1_LOOK}>
      <UploadSessionProvider>
        <SpeakerProfilesContext.Provider
          value={speakerProfiles(fixture.speakers)}
        >
          <WorkspaceAccessProvider value={FIXTURE_ACCESS}>
            <AcquisitionShell
              authenticated
              pageName="Report"
              homeHref="/review-fixture/report/story"
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
                  {clean ? null : (
                    <p className={styles.banner} role="note">
                      Development fixture · fictional data · no account,
                      recording or provider call
                    </p>
                  )}
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
                        languageLabel={fixture.language}
                        sourceLabel={
                          clean
                            ? "Call recording"
                            : "Fictional fixture transcript"
                        }
                        label={{
                          displayName: title,
                          revision: 1,
                        }}
                        claimed
                        busy={false}
                        canDownload={false}
                        canRequestDeletion
                        deletionDisabled
                        onOpenTranscript={() => setTranscriptReaderOpen(true)}
                        onAnalyseAnother={() =>
                          setStatus(
                            "Would open New analysis. Nothing was sent.",
                          )
                        }
                        visual={
                          <CallMap
                            callId={FIXTURE_CALL_ID}
                            transcript={transcript}
                            report={amitReport}
                            durationMs={FIXTURE_DURATION_MS}
                            onSelectEvidence={seek}
                            onSeek={playFrom}
                          />
                        }
                        context={
                          <CallContext
                            callId={FIXTURE_CALL_ID}
                            report={amitReport}
                            transcript={transcript}
                          />
                        }
                        compactVisual={
                          <CallMapMini
                            report={amitReport}
                            durationMs={FIXTURE_DURATION_MS}
                            onSeek={playFrom}
                          />
                        }
                        onDownload={() => {}}
                        onRequestDeletion={() => {}}
                      />
                      <ReportModes
                        fixture
                        fixtureLook={coach ? COACH_LOOK : undefined}
                        illustration={example ? exampleView(example) : null}
                        documentData={{
                          report: amitReport,
                          transcript,
                          title,
                        }}
                        label="Explore your sales report"
                        lightSurface={resolvedTheme !== "dark"}
                        boundCallId={FIXTURE_CALL_ID}
                        onSelectEvidence={selectSource}
                        panels={[
                          {
                            id: "overview",
                            label: "Overview",
                            content: (
                              <OverviewHook
                                report={amitReport}
                                transcript={transcript}
                                callId={FIXTURE_CALL_ID}
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
                                report={amitReport}
                                callId={FIXTURE_CALL_ID}
                                transcript={transcript}
                                onSelectEvidence={seek}
                                onSelectContextualPlayback={(
                                  _selection,
                                  title,
                                ) =>
                                  setStatus(
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
                                  report={amitReport}
                                  durationMs={FIXTURE_DURATION_MS}
                                  onSeek={playFrom}
                                />
                                <ProspectSnapshot
                                  report={amitReport}
                                  callId={FIXTURE_CALL_ID}
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
                                report={amitReport}
                                callId={FIXTURE_CALL_ID}
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
                                dimensions={amitReport.dimensions}
                                callId={FIXTURE_CALL_ID}
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
                                callId={FIXTURE_CALL_ID}
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
                            id: "raw-data",
                            label: "Raw data",
                            content: (
                              <ReportRawData
                                callId={FIXTURE_CALL_ID}
                                transcript={transcript}
                                report={amitReport}
                                durationMs={FIXTURE_DURATION_MS}
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
                        report={amitReport}
                        callId={FIXTURE_CALL_ID}
                        callTitle={title}
                        onSeek={playFrom}
                        audioAvailable
                      />
                      {clean ? null : (
                        <p
                          className={styles.status}
                          role="status"
                          aria-label="Fixture action status"
                          aria-live="polite"
                        >
                          {status}
                        </p>
                      )}
                    </section>
                    <CallAudioDock
                      audioRef={audio}
                      src=""
                      durationMs={FIXTURE_DURATION_MS}
                      title={clean ? title : "Fictional fixture · no audio"}
                    />
                  </SourceWaveformProvider>
                </div>
              </div>
            </AcquisitionShell>
          </WorkspaceAccessProvider>
        </SpeakerProfilesContext.Provider>
      </UploadSessionProvider>
    </ReportLookContext.Provider>
  );
}
