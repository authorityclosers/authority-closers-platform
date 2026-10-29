"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button } from "../ui/kit";
import { notify } from "../notice-center";
import {
  setupStatus,
  setupOpen,
  recorderOpen,
  pickRecordingsFolder,
  onPhoneSignal,
  autoCaptureRetry,
  type SetupStatus,
  type AutoCaptureStatus,
} from "../leads/native-phone";
import styles from "./capture-guard.module.css";

// Optional evidence from newer native bridges; absence always means unknown.
type HealthEvidence = AutoCaptureStatus & {
  lastRecordingSeenMs?: number | null;
};

function waiting(calls: number | undefined): string {
  if (!calls) return "Your next lead calls wait on this phone.";
  return calls === 1
    ? "1 lead call waits on this phone."
    : `${calls} lead calls wait on this phone.`;
}
type Fix = "profile" | "retry" | "folder" | "battery" | "leads" | null;
// Why calls wait (Redmi real-call test, 30 Oct 2026: each of these used to lose a call silently).
const reasons: Record<
  string,
  { title: string; body: (calls?: number) => string; fix: Fix }
> = {
  profile: {
    title: "Add your name and phone to upload calls",
    body: (calls) =>
      `${waiting(calls)} Sales Xray uploads calls only once your profile has your name and phone number. They upload by themselves after.`,
    fix: "profile",
  },
  allowance: {
    title: "Call minutes used up",
    body: (calls) =>
      `${waiting(calls)} They upload by themselves when your workspace has minutes again.`,
    fix: "retry",
  },
  signed_out: {
    title: "Sign in on this phone to upload calls",
    body: (calls) =>
      `${waiting(calls)} They upload by themselves once Sales Xray is signed in here.`,
    fix: "retry",
  },
  consent: {
    title: "Automatic uploads turned off",
    body: () =>
      "Automatic analysis is off for you or its terms changed. Turn it on, then turn uploads on below.",
    fix: null,
  },
  notices: {
    title: "Automatic uploads turned off",
    body: () =>
      "Upload notices are blocked, so Undo can't show. Allow upload notices, then turn uploads on below.",
    fix: null,
  },
  workspace: {
    title: "Calls wait for your organisation",
    body: (calls) =>
      `${waiting(calls)} Switch to your organisation workspace to upload them.`,
    fix: null,
  },
  folder: {
    title: "Pick your recordings folder again",
    body: (calls) =>
      `${waiting(calls)} Sales Xray can no longer read the recordings folder.`,
    fix: "folder",
  },
  network: {
    title: "Your phone is holding back uploads",
    body: (calls) =>
      `${waiting(calls)} Set Sales Xray's battery use to No restrictions so it can upload with the app closed.`,
    fix: "battery",
  },
  access: {
    title: "Uploads are waiting",
    body: (calls) =>
      `${waiting(calls)} Sales Xray tries again every hour, or now with Try again.`,
    fix: "retry",
  },
  review: {
    title: "A call needs you",
    body: (calls) =>
      `${calls === 1 ? "1 lead call" : `${calls ?? "Some"} lead calls`} couldn't upload by itself. Open the lead to upload its recording by hand.`,
    fix: "leads",
  },
  expired: {
    title: "Some calls were too old to upload",
    body: () =>
      "Recordings older than 3 days are not uploaded by themselves. Open the lead to add one by hand.",
    fix: "leads",
  },
};
/** The one reason calls wait right now, with its fix; nothing when all is well or the app is older. */
export function CaptureAttention({
  status,
  onRetry,
  onFolder,
  onBattery,
}: {
  status: AutoCaptureStatus | null;
  onRetry?: () => void;
  onFolder: () => void;
  onBattery?: () => void;
}) {
  const reason = status?.health ? reasons[status.health] : undefined;
  if (!reason) return null;
  return (
    <div
      className={styles.attention}
      role="status"
      data-reason={status?.health}
    >
      <span>
        <strong>{reason.title}</strong>
        <small>{reason.body(status?.healthCalls)}</small>
      </span>
      {reason.fix === "profile" ? (
        <Link href="/settings/profile">Open Profile</Link>
      ) : reason.fix === "folder" ? (
        <Button variant="ghost" onClick={onFolder}>
          Pick folder
        </Button>
      ) : reason.fix === "battery" && onBattery ? (
        <Button variant="ghost" onClick={onBattery}>
          Fix battery
        </Button>
      ) : reason.fix === "leads" ? (
        <Link href="/leads">Open Leads</Link>
      ) : reason.fix === "retry" && onRetry ? (
        <Button variant="ghost" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
export function CaptureHealthView({
  setup,
  status,
  consentOn,
  onRecorder,
  onFolder,
  onRefresh,
  onRetry,
  onBattery,
  checkedAt = null,
}: {
  setup: SetupStatus | null;
  status: HealthEvidence | null;
  consentOn: boolean;
  /** When this phone last answered the check; the age is counted from it, never read in render. */
  checkedAt?: number | null;
  onRecorder: () => void;
  onFolder: () => void;
  onRefresh: () => void;
  onRetry?: () => void;
  onBattery?: () => void;
}) {
  const privateFiles = setup?.recorder?.kind === "private";
  const recording = setup?.recorder?.recording;
  const lastSeen = privateFiles
    ? null
    : (setup?.recorder?.newestMs ?? status?.lastRecordingSeenMs);
  const ago =
    lastSeen && checkedAt !== null && lastSeen <= checkedAt
      ? Math.max(0, Math.floor((checkedAt - lastSeen) / 60_000))
      : null;
  return (
    <section id="calls-setup" aria-label="Calls setup check">
      <h3>Calls setup check</h3>
      <CaptureAttention
        status={status}
        onRetry={onRetry}
        onFolder={onFolder}
        onBattery={onBattery}
      />
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
            {status?.pending
              ? ` · ${status.pending === 1 ? "1 call" : `${status.pending} calls`} on the way`
              : ""}
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
  onStatus,
}: {
  status: AutoCaptureStatus | null;
  consentOn: boolean;
  /** The phone's answer after Try again. */
  onStatus?: (next: AutoCaptureStatus) => void;
}) {
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const answered = useCallback((next: SetupStatus | null) => {
    setSetup(next);
    setCheckedAt(Date.now());
  }, []);
  const refresh = useCallback(() => {
    void setupStatus().then(answered);
  }, [answered]);
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
      checkedAt={checkedAt}
      onRefresh={refresh}
      onRetry={() => {
        void autoCaptureRetry().then((next) => {
          if (next) onStatus?.(next);
          notify({
            id: "capture-retry",
            tone: "info",
            title: "Checking your waiting calls",
            message: "Calls whose problem is fixed upload in the next minute.",
            timeout: 5_000,
          });
        });
      }}
      onBattery={() => {
        void setupOpen("battery").then((opened) => {
          if (!opened)
            notify({
              id: "capture-health",
              title: "Open your phone's battery settings",
              message:
                "Find Sales Xray in Settings → Apps → Battery and choose No restrictions.",
              tone: "info",
            });
        });
      }}
      onRecorder={() => {
        void recorderOpen("settings").then((opened) => {
          if (!opened) explain();
        });
      }}
      onFolder={() => {
        void pickRecordingsFolder().then((next) => {
          if (next) answered(next);
          else explain();
        });
      }}
    />
  );
}
