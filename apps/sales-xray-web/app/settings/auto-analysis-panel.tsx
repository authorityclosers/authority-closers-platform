"use client";

/**
 * Settings → Privacy: "Analyse my calls automatically" (owner, 26 Oct 2026,
 * approved for v0.96). On, it is the kit's switch, and turning it off asks
 * first: calls from then on wait for their tap. Off or "ask", it says so and
 * offers Turn on, which opens the sheet with the owner's words. In a personal
 * workspace it shows nothing.
 */
import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { Panel, Skeleton } from "../ui/kit";
import { StateSwitch } from "../ui/state-switch";
import {
  chooseAutoAnalysis,
  readAutoAnalysis,
  type AutoAnalysis,
} from "./auto-analysis-client";
import { AutoCapturePanel } from "./auto-capture-panel";
import { AutoAnalysisSheet } from "./auto-analysis-sheet";
import { autoCaptureSetup, autoCaptureStatus } from "../leads/native-phone";
import styles from "./sections.module.css";

/**
 * Agreeing again after the upload terms changed (SX-AUTOUPLOAD, production 16 Nov 2026: the provider switch made
 * every phone stop its uploads, and agreeing again here left them stopped). When this phone stopped its uploads
 * for that reason only, turning them back on follows the agreement: Android shows its own Turn on words first.
 * A seller who turned uploads off themselves is left as they chose.
 */
export async function resumeAfterAgreeing(): Promise<void> {
  const status = await autoCaptureStatus();
  if (!status?.supported || status.on) return;
  if (status.health !== "consent" && status.health !== "terms") return;
  try {
    await autoCaptureSetup(true, status.wifiOnly);
  } catch {
    // Not now, or the profile is incomplete: the uploads panel below says what is left.
  }
}

export function AutoAnalysisPanel() {
  const [view, setView] = useState<AutoAnalysis | "loading" | "failed">(
    "loading",
  );
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    readAutoAnalysis(controller.signal).then(setView, () => {
      if (!controller.signal.aborted) setView("failed");
    });
    return () => controller.abort();
  }, []);

  if (view === "failed" || (view !== "loading" && view.state === "unavailable"))
    return null;
  if (view === "loading")
    return (
      <Panel title="Calls">
        <Skeleton height={56} />
      </Panel>
    );

  const title = view.notice?.title ?? "Automatic analysis";
  return (
    <Panel title="Calls">
      {view.state === "on" ? (
        <StateSwitch
          icon={<Sparkles size={18} />}
          label={title}
          meaning={view.notice?.text ?? ""}
          onText={
            view.can_start
              ? "On: each call you record here is analysed as it arrives"
              : "On, but AI on calls is off for you: calls are saved, not analysed"
          }
          offText="Off: each call waits for your tap"
          chipOn="Automatic analysis on"
          chipOff="Automatic analysis off"
          on
          confirmOff={{
            title: "Stop analysing your calls automatically?",
            points: [
              "Calls you record from now on wait for your tap.",
              "Calls already analysed keep their reports.",
            ],
            confirm: "Turn off",
            keep: "Keep it on",
          }}
          onChange={async () =>
            setView(await chooseAutoAnalysis({ decision: "withdrawn" }))
          }
        />
      ) : (
        <div className={styles.note}>
          <span className={styles.noteIcon} aria-hidden="true">
            <Sparkles size={18} />
          </span>
          <span className={styles.noteText}>
            <strong>{title}</strong>
            <span>
              {view.state === "ask" && view.since
                ? "The words or the upload terms changed. Read them again to turn it back on."
                : "Off: each call waits for your tap."}
            </span>
          </span>
          {/* A switch like every other setting (v1.96): turning it on opens
              the sheet with the owner's words first. */}
          <button
            type="button"
            role="switch"
            aria-checked={false}
            aria-label={`Turn on ${title}`}
            className={styles.offSwitch}
            onClick={() => setAsking(true)}
          />
        </div>
      )}
      <AutoCapturePanel
        consentOn={view.can_start}
        consentGiven={view.state === "on"}
      />
      <AutoAnalysisSheet
        open={asking}
        onClose={() => setAsking(false)}
        onSaved={(next) => {
          setView(next);
          if (next.state === "on") void resumeAfterAgreeing();
        }}
      />
    </Panel>
  );
}
