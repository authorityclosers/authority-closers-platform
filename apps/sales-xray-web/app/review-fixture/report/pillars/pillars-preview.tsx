"use client";

import { useState } from "react";
import { ReportModes } from "../../../report-modes";
import { DipakOverview } from "../../../dipak-overview";
import { SalesSkills } from "../../../sales-skills";
import type { ReportEvidence } from "../../../report-contract";
import { syntheticReport, syntheticCallRecord } from "../synthetic-report";
import styles from "../../../report-pillar-screen.module.css";

export function PillarsPreview() {
  const [source, setSource] = useState<ReportEvidence | null>(null);
  const [closingKind, setClosingKind] = useState<"won" | "lost" | null>(null);
  const report = closingKind
    ? {
        ...syntheticReport,
        // Simulate a misleading analysis label, never a human-entered fact.
        story: {
          version: "report-story/1" as const,
          phases: [],
          outcome: {
            kind: closingKind,
            next_step_rung: "none" as const,
            next_step_when: null,
            evidence: syntheticReport.strengths[0].evidence,
          },
          next_step: null,
          prospect_commitments: [],
          seller_commitments: [],
        },
      }
    : syntheticReport;
  return (
    <main className={styles.preview} data-synthetic-report>
      <div className={styles.previewFrame}>
        <h1>Report · fictional display preview</h1>
        <p>
          No recording, customer, account, audio or provider call exists here.
        </p>
        <div
          className={styles.previewControls}
          aria-label="Fictional analysis labels"
        >
          {(["won", "lost"] as const).map((kind) => (
            <button
              key={kind}
              type="button"
              onClick={() => setClosingKind(kind)}
            >
              Simulate {kind} analysis
            </button>
          ))}
          <button type="button" onClick={() => setClosingKind(null)}>
            Older report
          </button>
        </div>
        <ReportModes
          structure="pillars"
          initialView="story"
          lightSurface={false}
          documentData={{
            report,
            callRecord: syntheticCallRecord,
            callLength: "00:35",
            title: "Fictional Report pillars",
          }}
          panels={[
            {
              id: "overview",
              label: "Overview",
              content: (
                <DipakOverview
                  showHeading={false}
                  report={syntheticReport}
                  onSelectEvidence={setSource}
                  callRecord={syntheticCallRecord}
                />
              ),
            },
            {
              id: "skills",
              label: "Sales skills",
              content: (
                <SalesSkills
                  dimensions={syntheticReport.dimensions}
                  onSelectEvidence={setSource}
                />
              ),
            },
          ]}
          onSelectEvidence={setSource}
        />
        <aside role="status" className={styles.previewSource}>
          {source ? (
            <p>{source.quote}</p>
          ) : (
            <p>Select a source to inspect the fictional words.</p>
          )}
          No audio exists in this preview.
        </aside>
      </div>
    </main>
  );
}
