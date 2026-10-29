"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { applyTheme } from "../../lightbox/theme";
import { CaptureStateLabel } from "../../leads/auto-capture-state";
import { CaptureRatesView } from "../../capture-guard/capture-rates";
import { CaptureHealthView } from "../../capture-guard/capture-health";
import { Panel } from "../../ui/kit";
import { parseSetup } from "../../leads/native-phone";
import guardStyles from "../../capture-guard/capture-guard.module.css";
import styles from "../auto-capture/preview.module.css";
const setup = parseSetup({
  checks: {},
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
  const panel = useSearchParams().get("panel") ?? "all";
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.getAttribute("data-theme") ?? "light";
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () =>
      applyTheme(root, "system", query.matches ? "dark" : "light");
    apply();
    query.addEventListener("change", apply);
    return () => {
      query.removeEventListener("change", apply);
      applyTheme(
        root,
        previous === "dark" ? "dark" : "light",
        previous === "dark" ? "dark" : "light",
      );
    };
  }, []);
  const [action, setAction] = useState<string | null>(null);
  return (
    <main className={styles.page}>
      <h1>Call capture</h1>
      {panel === "all" || panel === "states" ? (
        <Panel title="Alex Example’s lead calls">
          <div className={guardStyles.content}>
            <ul className={styles.calls}>
              {[
                "waiting",
                "uploaded",
                "analysing",
                "report_ready",
                "missing",
              ].map((state, index) => (
                <li key={state}>
                  <strong>Lead call {index + 1}</strong>
                  <CaptureStateLabel state={state} />
                </li>
              ))}
            </ul>
          </div>
        </Panel>
      ) : null}
      {panel === "all" || panel === "setup" ? (
        <Panel title="Calls">
          <div className={guardStyles.content}>
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
              Automatic uploads are off. Give standing consent before turning
              them on.
            </div>
          </div>
        </Panel>
      ) : null}
      {panel === "all" || panel === "rates" ? (
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
      ) : null}
    </main>
  );
}
