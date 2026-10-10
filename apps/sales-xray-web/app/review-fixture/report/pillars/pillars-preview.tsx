"use client";

import { useState } from "react";
import { ReportModes } from "../../../report-modes";
import type { ReportEvidence } from "../../../report-contract";
import { syntheticReport, syntheticCallRecord } from "../synthetic-report";
import styles from "../../../report-pillar-screen.module.css";

export function PillarsPreview() {
  const [source, setSource] = useState<ReportEvidence | null>(null);
  return (
    <main className={styles.preview} data-synthetic-report>
      <div className={styles.previewFrame}>
        <h1>Report · fictional display preview</h1>
        <p>
          No recording, customer, account, audio or provider call exists here.
        </p>
        <ReportModes
          structure="pillars"
          initialView="reading"
          lightSurface={false}
          documentData={{
            report: syntheticReport,
            callRecord: syntheticCallRecord,
            callLength: "00:35",
            title: "Fictional Report pillars",
          }}
          panels={[]}
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
