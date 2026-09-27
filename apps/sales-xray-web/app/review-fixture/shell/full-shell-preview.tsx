"use client";

import { useRef, useState } from "react";

import type { Allowance } from "../../acquisition-client";
import { AcquisitionShell } from "../../acquisition-shell";
import { CallAudioDock } from "../../call-audio-dock";
import { DipakOverview } from "../../dipak-overview";
import { UploadSessionProvider } from "../../hooks/upload-session";
import { NextCallPlan } from "../../next-call-plan";
import { ProspectSnapshot } from "../../prospect-snapshot";
import type { ReportEvidence } from "../../report-contract";
import { ReportHeader } from "../../report-header";
import { ReportModes } from "../../report-modes";
import { ReportMoments } from "../../report-moments";
import {
  ReportTranscript,
  formatTranscriptTime,
} from "../../report-transcript";
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

/**
 * The actual Sales Xray shell, report header, report sections and call dock
 * mounted with invented data for local visual review. No recording, account,
 * analysis or provider call exists; actions only report what they would do.
 */
export function FullShellPreview() {
  const audio = useRef<HTMLAudioElement>(null);
  const [status, setStatus] = useState(
    "Fictional fixture. Actions here do not reach any service.",
  );
  const selectSource = (evidence: ReportEvidence, title: string) =>
    setStatus(
      `Selected ${formatTranscriptTime(evidence.start_ms)}–${formatTranscriptTime(evidence.end_ms)} · ${title}. No audio exists in this fixture.`,
    );

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
            data-theme="light"
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
                  data-lx-surface="light"
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
                    onAnalyseAnother={() =>
                      setStatus("Would open New analysis. Nothing was sent.")
                    }
                    onDownload={() => {}}
                    onRequestDeletion={() => {}}
                  />
                  <ReportModes
                    label="Explore your sales report"
                    boundCallId="00000000-0000-4000-8000-000000000002"
                    panels={[
                      {
                        id: "overview",
                        label: "Overview",
                        content: (
                          <DipakOverview
                            showHeading={false}
                            report={syntheticReport}
                            onSelectEvidence={selectSource}
                            durationMs={FIXTURE_DURATION_MS}
                          />
                        ),
                      },
                      {
                        id: "prospect",
                        label: "Prospect",
                        content: (
                          <ProspectSnapshot
                            report={syntheticReport}
                            onSelectEvidence={selectSource}
                          />
                        ),
                      },
                      {
                        id: "moments",
                        label: "Moments",
                        content: (
                          <ReportMoments
                            report={syntheticReport}
                            onSelectEvidence={selectSource}
                          />
                        ),
                      },
                      {
                        id: "skills",
                        label: "Sales skills",
                        compactLabel: "Skills",
                        content: (
                          <SalesSkills
                            dimensions={syntheticReport.dimensions}
                            onSelectEvidence={(evidence) =>
                              selectSource(evidence, "Sales skill excerpt")
                            }
                          />
                        ),
                      },
                      {
                        id: "next-call-plan",
                        label: "Next-call plan",
                        compactLabel: "Next-call",
                        content: (
                          <NextCallPlan
                            report={syntheticReport}
                            onSelectEvidence={selectSource}
                          />
                        ),
                      },
                      {
                        id: "transcript",
                        label: "Transcript",
                        content: (
                          <ReportTranscript
                            transcript={{
                              ...baseFixture.transcript,
                              duration_ms: FIXTURE_DURATION_MS,
                            }}
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
                    ]}
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
