"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button } from "../ui/kit";
import { notify } from "../notice-center";
import {
  setupStatus,
  recorderOpen,
  pickRecordingsFolder,
  onPhoneSignal,
  type SetupStatus,
  type AutoCaptureStatus,
} from "../leads/native-phone";
import styles from "./capture-guard.module.css";

// Optional evidence from newer native bridges; absence always means unknown.
type HealthEvidence = AutoCaptureStatus & {
  lastRecordingSeenMs?: number | null;
};
export function CaptureHealthView({
  setup,
  status,
  consentOn,
  onRecorder,
  onFolder,
  onRefresh,
}: {
  setup: SetupStatus | null;
  status: HealthEvidence | null;
  consentOn: boolean;
  onRecorder: () => void;
  onFolder: () => void;
  onRefresh: () => void;
}) {
  const privateFiles = setup?.recorder?.kind === "private";
  const recording = setup?.recorder?.recording;
  const lastSeen = privateFiles
    ? null
    : (setup?.recorder?.newestMs ?? status?.lastRecordingSeenMs);
  const ago =
    lastSeen && lastSeen <= Date.now()
      ? Math.max(0, Math.floor((Date.now() - lastSeen) / 60_000))
      : null;
  return (
    <section id="calls-setup" aria-label="Calls setup check">
      <h3>Calls setup check</h3>
      <div className={styles.check}>
        <span>
          <strong>Is the phone saving recordings?</strong>
          <small>
            {privateFiles
              ? "This Phone app keeps recordings private. Sales Xray cannot read them."
              : recording === "on"
                ? "Call recording is on. Make a test call to check the saved file."
                : recording === "off"
                  ? "Call recording is off."
                  : "Not confirmed by this phone. Check its recorder settings."}
          </small>
        </span>
        <Button variant="ghost" onClick={onRecorder}>
          Fix recorder
        </Button>
      </div>
      <div className={styles.check}>
        <span>
          <strong>Is the recordings folder granted?</strong>
          <small>
            {setup
              ? setup.folderPicked
                ? "A recordings folder is selected."
                : "No recordings folder selected."
              : "Open Sales Xray on your phone to check."}
          </small>
        </span>
        <Button variant="ghost" onClick={onFolder}>
          Fix folder
        </Button>
      </div>
      <div className={styles.check}>
        <span>
          <strong>When was a recording last seen?</strong>
          <small>
            {ago === null
              ? "This app has not reported when it last saw a recording."
              : ago < 1
                ? "Last readable recording saved less than a minute ago."
                : ago < 60
                  ? `Last readable recording saved ${ago} minutes ago.`
                  : `Last readable recording saved ${Math.floor(ago / 60)} hours ago.`}
          </small>
        </span>
        <Button variant="ghost" onClick={onRefresh}>
          Check again
        </Button>
      </div>
      <div className={styles.check}>
        <span>
          <strong>Are auto-upload and consent on?</strong>
          <small>
            {status?.on ? "Auto-upload on" : "Auto-upload off or unavailable"} ·{" "}
            {consentOn ? "Standing consent given" : "Standing consent needed"}
          </small>
        </span>
        <Link
          href={
            status?.supported ? "#automatic-call-uploads" : "/settings/devices"
          }
        >
          Fix uploads
        </Link>
      </div>
      {privateFiles ? (
        <p>
          Company calling can record calls without reading this phone&apos;s
          private folder. It is being prepared for your company.{" "}
          <Link href="/settings/organisation">Open company settings</Link>
        </p>
      ) : null}
    </section>
  );
}
export function CaptureHealth({
  status,
  consentOn,
}: {
  status: AutoCaptureStatus | null;
  consentOn: boolean;
}) {
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const refresh = useCallback(() => {
    void setupStatus().then(setSetup);
  }, []);
  useEffect(() => {
    refresh();
    return onPhoneSignal((signal) => {
      if (signal === "resume" || signal === "recordings") refresh();
    });
  }, [refresh]);
  const explain = () =>
    notify({
      id: "capture-health",
      title: "Open your phone's recorder settings",
      message:
        "Use the Phone app on your phone to check call recording, then return here.",
      tone: "info",
    });
  return (
    <CaptureHealthView
      setup={setup}
      status={status}
      consentOn={consentOn}
      onRefresh={refresh}
      onRecorder={() => {
        void recorderOpen("settings").then((opened) => {
          if (!opened) explain();
        });
      }}
      onFolder={() => {
        void pickRecordingsFolder().then((next) => {
          if (next) setSetup(next);
          else explain();
        });
      }}
    />
  );
}
