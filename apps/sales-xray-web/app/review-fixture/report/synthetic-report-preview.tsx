"use client";

import { useState } from "react";
import type { ReportEvidence } from "../../report-contract";
import { ReportModes } from "../../report-modes";
import { formatTranscriptTime } from "../../report-transcript";
import { SalesSkills } from "../../sales-skills";
import { NextCallPlan } from "../../next-call-plan";
import { syntheticReport } from "./synthetic-report";
import styles from "./synthetic-report-preview.module.css";

type SelectedSource = { evidence: ReportEvidence; title: string };

export function SyntheticReportPreview() {
  const [source, setSource] = useState<SelectedSource | null>(null);
  const selectSource = (evidence: ReportEvidence, title: string) =>
    setSource({ evidence, title });

  return (
    <main
      id="main-content"
      className={styles.page}
      data-synthetic-report="true"
    >
      <div className={styles.frame}>
        <header className={styles.heading}>
          <div>
            <p className={styles.eyebrow}>Sales Xray · local visual review</p>
            <h1>Synthetic report preview</h1>
            <p>
              Actual report components with invented dialogue. No recording,
              account, analysis, or provider call exists here.
            </p>
          </div>
          <span className={styles.badge}>Synthetic display only</span>
        </header>
        <aside className={styles.disclaimer} aria-label="Review limits">
          This preview checks responsive layout, source navigation, and
          accessibility. It does not show a validated coaching result.
        </aside>
        <ReportModes
          label="Synthetic report sections"
          panels={[
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
          ]}
        />
        <aside className={styles.source} role="status" aria-live="polite">
          {source ? (
            <>
              <strong>Selected synthetic source · {source.title}</strong>
              <p>
                {formatTranscriptTime(source.evidence.start_ms)}–
                {formatTranscriptTime(source.evidence.end_ms)} ·{" "}
                {source.evidence.quote}
              </p>
              <small>No audio exists in this display fixture.</small>
            </>
          ) : (
            <>
              <strong>Source interaction preview</strong>
              <p>
                Select a source moment to inspect its invented quote and
                timestamp.
              </p>
              <small>No audio exists in this display fixture.</small>
            </>
          )}
        </aside>
      </div>
    </main>
  );
}
