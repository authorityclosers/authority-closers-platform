"use client";
import { useEffect, useState } from "react";
import { Button } from "../ui/kit";
import { notify } from "../notice-center";
import {
  autoCaptureStatus,
  autoCaptureSetup,
  pickRecordingsFolder,
  askNotifications,
  type AutoCaptureStatus,
} from "../leads/native-phone";

import styles from "./auto-capture-panel.module.css";

/** Seller: choose a folder and enable upload after the native disclosure. */
export function AutoCapturePanel({ consentOn }: { consentOn: boolean }) {
  const [status, setStatus] = useState<AutoCaptureStatus | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void autoCaptureStatus()
      .then(async (next) => {
        if (next?.on && !consentOn)
          setStatus(await autoCaptureSetup(false, next.wifiOnly));
        else setStatus(next);
      })
      .catch(() => undefined);
  }, [consentOn]);
  if (!status?.supported) return null;
  const save = async (on: boolean, wifi: boolean) => {
    setBusy(true);
    try {
      setStatus(await autoCaptureSetup(on, wifi));
    } catch {
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
      <p>
        <strong>Automatic call uploads</strong>
      </p>
      <p>
        {status.on
          ? "On: matched lead calls upload in the background after a 60-second Undo window."
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
        <select
          aria-label="Upload network"
          disabled={busy}
          value={status.wifiOnly ? "wifi" : "any"}
          onChange={(event) => {
            const wifi = event.target.value === "wifi";
            if (status.on) void save(true, wifi);
            else setStatus({ ...status, wifiOnly: wifi });
          }}
        >
          <option value="wifi">Wi-Fi only</option>
          <option value="any">Any network</option>
        </select>
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
        <p>Turn automatic analysis on above before enabling uploads.</p>
      ) : null}
    </div>
  );
}
