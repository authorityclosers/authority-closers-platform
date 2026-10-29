"use client";
import { useState } from "react";
import { CaptureStateLabel } from "../../leads/auto-capture-state";
import { CaptureRatesView } from "../../capture-guard/capture-rates";
import { CaptureHealthView } from "../../capture-guard/capture-health";
import { Panel } from "../../ui/kit";
import { parseSetup } from "../../leads/native-phone";
import styles from "../auto-capture/preview.module.css";
const setup = parseSetup({
  family: "other",
  model: "Example phone",
  folderPicked: false,
  recorderProfile: {
    kind: "private",
    recording: "private",
    dialerLabel: "Phone",
    folders: [],
  },
});
export function CaptureGuardPreview() {
  const [action, setAction] = useState<string | null>(null);
  return (
    <main className={styles.page}>
      <h1>Call capture</h1>
      <Panel title="Alex Example’s lead calls">
        <ul className={styles.calls}>
          {["waiting", "uploaded", "analysing", "report_ready", "missing"].map(
            (state, index) => (
              <li key={state}>
                <strong>Lead call {index + 1}</strong>
                <CaptureStateLabel state={state} />
              </li>
            ),
          )}
        </ul>
      </Panel>
      <Panel title="Calls">
        <CaptureHealthView
          setup={setup}
          status={{ supported: true, on: false, wifiOnly: true }}
          consentOn={false}
          onRecorder={() => setAction("Recorder settings requested")}
          onFolder={() => setAction("Recordings folder picker requested")}
          onRefresh={() => setAction("Recording check requested")}
        />
        {action ? <p role="status">{action}</p> : null}
        <div id="automatic-call-uploads">
          Automatic uploads are off. Give standing consent before turning them
          on.
        </div>
      </Panel>
      <CaptureRatesView
        rates={[
          {
            person_id: "alex",
            name: "Alex Example",
            day: "2026-10-29",
            calls: 10,
            received: 3,
            analysed: 2,
            rate: 30,
            needs_fix: true,
          },
          {
            person_id: "sam",
            name: "Sam Example",
            day: "2026-10-29",
            calls: 10,
            received: 9,
            analysed: 8,
            rate: 90,
            needs_fix: false,
          },
        ]}
      />
    </main>
  );
}
