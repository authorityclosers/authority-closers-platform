"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "../ui/kit";
import { Picker } from "../ui/picker";
import { notify } from "../notice-center";
import {
  autoCaptureStatus,
  autoCaptureSetup,
  pickRecordingsFolder,
  askNotifications,
  type AutoCaptureStatus,
  onPhoneSignal,
} from "../leads/native-phone";

import { CaptureHealth } from "../capture-guard/capture-health";
import { openCaptureSetup } from "../capture-setup/capture-setup-gate";
import styles from "./auto-capture-panel.module.css";

/** Seller: choose a folder and enable upload after the native disclosure. */
export function AutoCapturePanel({
  consentOn,
  consentGiven = consentOn,
}: {
  consentOn: boolean;
  consentGiven?: boolean;
}) {
  const [status, setStatus] = useState<AutoCaptureStatus | null>(null);
  const [needsProfile, setNeedsProfile] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const refresh = () =>
      void autoCaptureStatus()
        .then(async (next) => {
          if (next?.on && !consentOn)
            setStatus(await autoCaptureSetup(false, next.wifiOnly));
          else setStatus(next);
        })
        .catch(() => undefined);
    refresh();
    return onPhoneSignal((signal) => {
      if (signal === "resume" || signal === "recordings") refresh();
    });
  }, [consentOn]);
  if (!status?.supported)
    return <CaptureHealth status={status} consentOn={consentGiven} />;
  const save = async (on: boolean, wifi: boolean) => {
    setBusy(true);
    try {
      setStatus(await autoCaptureSetup(on, wifi));
    } catch (error) {
      const code = error instanceof Error ? error.message : "";
      // The edge refuses every upload while the profile is incomplete (Redmi test, 30 Oct 2026).
      if (code === "profile_required") {
        setNeedsProfile(true);
        notify({
          id: "auto-capture",
          tone: "error",
          title: "Complete your profile first",
          message:
            "Sales Xray uploads calls only once your profile has your name and phone number.",
        });
      } else
        notify({
          id: "auto-capture",
          tone: "error",
          title: "Automatic upload didn't change",
          message:
            "Check your folder grant, notifications and automatic analysis consent, then try again.",
        });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.capture}>
      <CaptureHealth
        status={status}
        consentOn={consentGiven}
        onStatus={setStatus}
      />
      <div id="automatic-call-uploads" />
      <p>
        <strong>Automatic call uploads</strong>
      </p>
      <p>
        {status.on
          ? "On: matched lead calls upload in the background after a 60-second Undo window."
          : status.offSinceMs
            ? "Off: recordings stay on your phone. Turning uploads on again asks whether to include the calls saved while off."
            : "Off: recordings stay on your phone until you choose to upload them."}
      </p>
      <p>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => void pickRecordingsFolder()}
        >
          Choose recordings folder
        </Button>
      </p>
      <p>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => void askNotifications()}
        >
          Allow upload notices
        </Button>
      </p>
      <label>
        Upload using{" "}
        <Picker
          title="Upload network"
          ariaLabel="Upload network"
          disabled={busy}
          value={status.wifiOnly ? "wifi" : "any"}
          options={[
            { key: "wifi", label: "Wi-Fi only" },
            { key: "any", label: "Any network" },
          ]}
          onChange={(key) => {
            const wifi = key === "wifi";
            if (status.on) void save(true, wifi);
            else setStatus({ ...status, wifiOnly: wifi });
          }}
        />
      </label>
      <p>
        <Button
          variant={status.on ? "ghost" : "primary"}
          disabled={busy || (!status.on && !consentOn)}
          onClick={() => void save(!status.on, status.wifiOnly)}
        >
          {status.on ? "Turn uploads off" : "Turn uploads on"}
        </Button>
      </p>
      {!consentOn ? (
        <p>Uploads need standing consent and AI on calls enabled for you.</p>
      ) : null}
      <p>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => openCaptureSetup()}
        >
          Go through call capture setup
        </Button>
      </p>
      {needsProfile ? (
        <p role="status">
          Complete your profile first: uploads need your name and phone number.{" "}
          <Link href="/settings/profile">Open Profile</Link>
        </p>
      ) : null}
    </div>
  );
}
