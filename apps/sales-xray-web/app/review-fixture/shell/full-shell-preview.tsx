"use client";

import type { Allowance } from "../../acquisition-client";
import { SampleReportView } from "../../analysis/sample/sample-report-view";
import { UploadSessionProvider } from "../../hooks/upload-session";
import { WorkspaceAccessProvider } from "../../workspace-access";
import { syntheticReport } from "../report/synthetic-report";
import baseFixture from "../../../tests/fixtures/dipak-overview.json";

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
 * mounted with invented data for local visual review: the report view the
 * sample report uses (analysis/sample/sample-report-view.tsx), as a fixture.
 * No recording, account, analysis or provider call exists; actions only
 * report what they would do.
 */
export function FullShellPreview() {
  const transcript = {
    ...baseFixture.transcript,
    duration_ms: FIXTURE_DURATION_MS,
  };
  return (
    <UploadSessionProvider>
      <WorkspaceAccessProvider value={FIXTURE_ACCESS}>
        <SampleReportView
          variant="fixture"
          homeHref="/review-fixture/shell"
          allowance={FIXTURE_ALLOWANCE}
          banner={
            <span>
              Development fixture · fictional data · no account, recording or
              provider call
            </span>
          }
          data={{
            callId: FIXTURE_CALL_ID,
            report: syntheticReport,
            transcript,
            durationMs: FIXTURE_DURATION_MS,
            languageLabel: "Marathi + English",
            sourceLabel: "Fictional fixture transcript",
            title: "Fictional sample call",
            audioSrc: "",
          }}
        />
      </WorkspaceAccessProvider>
    </UploadSessionProvider>
  );
}
