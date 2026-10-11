"use client";

import { useState } from "react";
import fixture from "../../../../tests/fixtures/dipak-overview.json";
import { DipakOverview } from "../../../dipak-overview";
import { formatClock } from "../../../lightbox/time";
import {
  parseJobResponse,
  parseTranscript,
  type ReportEvidence,
} from "../../../report-contract";
import { ReportModes } from "../../../report-modes";
import styles from "../../../report-pillar-screen.module.css";

// Fictional native report -> the real parser -> the real Report views. Null
// optional metadata must preserve the saved findings and honest skill gaps.
const transcript = parseTranscript(
  fixture.transcript,
  fixture.report.source_sha256,
);
const report = parseJobResponse(
  {
    id: "fictional-legacy-report",
    state: "completed",
    message: "Report ready.",
    report: {
      ...fixture.report,
      summary_evidence: null,
      verdict_evidence: null,
      overview: null,
      story: null,
      dimensions: fixture.report.dimensions.map((dimension) => ({
        ...dimension,
        evidence: null,
        call_state: null,
      })),
    },
  },
  {
    sourceSha256: transcript.source_sha256,
    durationMs: transcript.duration_ms,
    transcript,
  },
).report!;

export function LegacyReportPreview() {
  const [source, setSource] = useState<ReportEvidence | null>(null);
  return (
    <main className={styles.preview} data-nullable-report>
      <div className={styles.previewFrame}>
        <h1>Saved Report · fictional nullable metadata</h1>
        <p>No account, recording, provider or data service is used here.</p>
        <ReportModes
          structure="pillars"
          initialView="story"
          lightSurface={false}
          documentData={{
            report,
            transcript,
            callRecord: null,
            callLength: formatClock(transcript.duration_ms),
            title: "Fictional saved Report",
          }}
          panels={[
            {
              id: "overview",
              label: "Overview",
              content: (
                <DipakOverview
                  showHeading={false}
                  report={report}
                  callRecord={null}
                  onSelectEvidence={setSource}
                />
              ),
            },
          ]}
          onSelectEvidence={setSource}
        />
        <aside role="status" className={styles.previewSource}>
          {source ? <p>{source.quote}</p> : <p>Select a fictional source.</p>}
          No audio exists in this preview.
        </aside>
      </div>
    </main>
  );
}
