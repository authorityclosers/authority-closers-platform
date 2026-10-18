"use client";

/**
 * Work calls logged by themselves (UX study item 5, like Salestrail and
 * Callyzer). Inside the Sales Xray phone app the phone reads its own call
 * history when the app opens and every 15 minutes, and puts calls with the
 * seller's leads on those leads, even ones made from the phone dialer. Only
 * lead numbers on the work SIM are sent; every other number stays on the
 * phone. A one-time card offers it; once it is on, a slim row says so, shows
 * when the phone last looked, and switches it off. Nothing shows in a browser
 * or in an older app.
 */

import { History, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "../ui/kit";
import { ago } from "./leads-client";
import {
  buzz,
  callLogSetup,
  callLogStatus,
  inPhoneApp,
  onPhoneSignal,
  type CallLogStatus,
} from "./native-phone";
import styles from "./leads.module.css";

const HIDE_KEY = "sx-leads-phone-log-card";

const NO_ACCESS =
  "Allow call history for Sales Xray in your phone's settings, then try again.";

/** The small line under "Logging work calls". */
export function phoneLogLine(status: CallLogStatus, now = new Date()): string {
  if (!status.access) return NO_ACCESS;
  if (status.state === "signed_out") return "Sign in again to keep logging.";
  const sim = status.sims.find((item) => item.id === status.sim)?.label;
  const checked = status.lastSyncMs
    ? `checked ${ago(new Date(status.lastSyncMs).toISOString(), now)}`
    : "checks when you open the app and every 15 minutes";
  return [sim, checked].filter(Boolean).join(" · ");
}

export function PhoneLogCard() {
  const [status, setStatus] = useState<CallLogStatus | null>(null);
  const [hidden, setHidden] = useState(false);
  const [sim, setSim] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!inPhoneApp()) return;
    let alive = true;
    const read = () =>
      void callLogStatus().then((next) => {
        if (!alive || !next) return;
        try {
          setHidden(localStorage.getItem(HIDE_KEY) === "hidden");
        } catch {
          // Storage blocked: offer it this visit.
        }
        setStatus(next);
        setSim((current) => current || next.sim || next.sims[0]?.id || "");
      });
    read();
    // The phone logged new calls, or the app came back: the line updates.
    const stop = onPhoneSignal((event) => {
      if (event === "calls" || event === "resume") read();
    });
    return () => {
      alive = false;
      stop();
    };
  }, []);

  if (!status || (!status.on && hidden)) return null;

  const turn = async (on: boolean) => {
    setBusy(true);
    setProblem(null);
    const next = await callLogSetup(on, sim);
    setBusy(false);
    if (!next) {
      setProblem("Your phone didn't answer. Try again.");
      return;
    }
    setStatus(next);
    setSim((current) => current || next.sim || next.sims[0]?.id || "");
    // With access given, a phone with two SIMs waits for the work SIM.
    if (on && !next.on)
      setProblem(
        next.access && next.sims.length > 1
          ? "Pick your work SIM, then turn it on."
          : NO_ACCESS,
      );
    else if (on) buzz("done");
  };

  if (status.on)
    return (
      <div className={styles.taking} data-place="row">
        <button
          type="button"
          role="switch"
          aria-checked
          className={styles.takingSwitch}
          disabled={busy}
          onClick={() => void turn(false)}
        >
          <span className={styles.takingTrack} aria-hidden="true">
            <span />
          </span>
          <span className={styles.takingLabel}>
            <strong>Logging work calls</strong>
            <small>{phoneLogLine(status)}</small>
          </span>
        </button>
        {problem ? (
          <p className={styles.error} role="alert">
            {problem}
          </p>
        ) : null}
      </div>
    );

  return (
    <section className={styles.phoneLogCard} aria-label="Log work calls">
      <History size={20} aria-hidden="true" />
      <span>
        <strong>Log your work calls by themselves.</strong>{" "}
        {problem ??
          "Calls with your leads from the phone dialer show on the lead and in your day. Other numbers never leave your phone."}
      </span>
      <Button
        variant="primary"
        className={styles.bannerAction}
        disabled={busy}
        onClick={() => void turn(true)}
      >
        {busy ? "Turning on…" : "Turn on"}
      </Button>
      <button
        type="button"
        className={styles.bannerClose}
        aria-label="Not now"
        onClick={() => {
          try {
            localStorage.setItem(HIDE_KEY, "hidden");
          } catch {
            // Storage blocked: hidden for this visit only.
          }
          setHidden(true);
        }}
      >
        <X size={16} aria-hidden="true" />
      </button>
      {status.sims.length > 1 ? (
        <div className={styles.phoneLogSims} role="group" aria-label="Work SIM">
          <span>Work SIM</span>
          {status.sims.map((item) => (
            <button
              key={item.id}
              type="button"
              className={styles.chip}
              aria-pressed={sim === item.id}
              onClick={() => setSim(item.id)}
            >
              {item.label || "SIM"}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}
