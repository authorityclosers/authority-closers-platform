"use client";

import { CallOutcomeEditor } from "../../../report-call-outcome";
import styles from "../../../prospect-information.module.css";

/** Invented unrecorded state; the fixture cannot save or update a stage. */
export function OutcomeFixture() {
  return (
    <main className={styles.preview}>
      <h1>Call outcome · fictional interaction</h1>
      <p>
        No call, person, recorded outcome, deal or server write exists here.
      </p>
      <CallOutcomeEditor
        scopeKey="fictional-account:fictional-call"
        value={null}
        canEdit
        onSave={async () => {
          throw new Error("This fixture has no persistence port.");
        }}
      />
    </main>
  );
}
