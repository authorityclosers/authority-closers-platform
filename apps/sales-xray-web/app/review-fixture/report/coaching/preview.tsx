"use client";

import { useState } from "react";
import { ReportModes } from "../../../report-modes";
import { WorkspaceAccessContext } from "../../../workspace-access";
import {
  fictionalCallCoaching,
  callCoachingBinding,
} from "../../../report-call-coaching.fixture";
import { parseCallCoaching } from "../../../report-call-coaching-client";
import { fictionalClip } from "../../../coaching/coaching.fixture";
import {
  parseAcquisitionReport,
  type ReportEvidence,
} from "../../../report-contract";
import {
  envelope,
  recordingId,
  submissionId,
  transcript,
} from "../../../../tests/acquisition-fixture";
import styles from "../../../report-pillar-screen.module.css";

const data = {
  report: parseAcquisitionReport(
    envelope,
    { submissionId, recordingId },
    transcript,
  ).report,
  transcript,
  recordingId,
  callCoaching: parseCallCoaching(
    { ...fictionalCallCoaching(), media_clips: [fictionalClip] },
    callCoachingBinding,
  ),
};
const access = {
  status: "ready" as const,
  authenticated: true,
  context: {
    personId: callCoachingBinding.personId,
    tenantId: callCoachingBinding.tenantId,
    sessionId: "00000000-0000-0000-0000-000000000008",
  },
  retry: () => {},
};
export function CallCoachingPreview() {
  const [source, setSource] = useState<ReportEvidence | null>(null);
  return (
    <WorkspaceAccessContext.Provider value={access}>
      <main className={styles.preview}>
        <div className={styles.previewFrame}>
          <h1>Call Coaching · fictional display</h1>
          <p>
            No account, real recording, provider or deployed API request exists
            here.
          </p>
          <ReportModes
            initialView="coaching"
            boundCallId={submissionId}
            lightSurface={false}
            documentData={data}
            panels={[
              {
                id: "overview",
                label: "Overview",
                content: <p>Fictional retained report.</p>,
              },
            ]}
            onSelectEvidence={(evidence) => setSource(evidence)}
          />
          <aside className={styles.previewSource} role="status">
            {source
              ? `${source.start_ms}–${source.end_ms} ms · ${source.quote}`
              : "Select a fictional source moment."}
          </aside>
        </div>
      </main>
    </WorkspaceAccessContext.Provider>
  );
}
