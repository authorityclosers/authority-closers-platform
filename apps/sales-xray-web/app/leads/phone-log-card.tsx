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
 *
 * Once on, it is the kit's StateSwitch (owner, 23 Oct 2026: switches that
 * matter say their state in words and ask before stopping): stopping asks
 * first, and when the phone can't log (no call history access, signed out)
 * the row says it isn't logging and why, though the switch is still on.
 */

import { History, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "../ui/kit";
import { StateSwitch } from "../ui/state-switch";
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

/**
 * `as`: "chip" draws only the small Logging calls chip once it is on (Leads'
 * toolbar, owner 22 Oct); "offer" only the card that offers it while off.
 */
export function PhoneLogCard({
  as = "both",
}: { as?: "both" | "chip" | "offer" } = {}) {
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
  if ((as === "chip" && !status.on) || (as === "offer" && status.on))
    return null;

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

  if (status.on) {
    // On, but the phone can't log: the row says so, and why.
    const stuck = !status.access || status.state === "signed_out";
    return (
      <StateSwitch
        icon={<History size={20} />}
        label="Logging work calls"
        meaning="While this is on, this phone puts calls with your leads on those leads, even ones from the phone's dialer. Other numbers stay on your phone."
        onText="Calls with your leads are logged"
        offText="Calls from this phone aren't logged"
        note={phoneLogLine(status)}
        chipOn="Logging calls"
        chipOff="Not logging calls"
        on
        hold={
          stuck
            ? {
                title: "Not logging right now",
                reason: phoneLogLine(status),
                chip: "Calls not logged",
              }
            : null
        }
        confirmOff={{
          title: "Stop logging work calls?",
          points: [
            "Calls from this phone, including ones from the phone's dialer, stop showing on your leads.",
            "Calls already logged stay on their leads.",
            "Turn it back on any time, from Leads or Settings, Selling.",
          ],
          confirm: "Stop logging",
          keep: "Keep logging",
        }}
        onChange={async (next) => {
          const saved = await callLogSetup(next, sim);
          if (!saved) throw new Error("Your phone didn't answer. Try again.");
          setStatus(saved);
        }}
        place={as === "chip" ? "chip" : "row"}
      />
    );
  }

  return (
    <section className={styles.phoneLogCard} aria-label="Log work calls">
      <History size={20} aria-hidden="true" />
      <span>
        <strong>Log work calls by themselves</strong>{" "}
        <small>
          {problem ??
            "Only calls with your leads. Other numbers stay on your phone."}
        </small>
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
