"use client";

/**
 * Review alerts on the phone (owner, 19 Oct): inside the Sales Xray Android
 * app, a one-time card on /review asks to turn on an alert for each new Report
 * to review. No Leads or workspace is needed. Once on, the phone's alert
 * address is re-sent quietly each visit, so a renewed address keeps working.
 * Nothing shows in a browser, in an older app, to someone who is not a gold
 * reviewer, or while alerts aren't set up on this server.
 */

import { BellRing, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  buzz,
  inPhoneApp,
  phoneStatus,
  pushEnable,
  pushStatus,
} from "../leads/native-phone";
import {
  readReviewPush,
  registerReviewPhone,
  type ReviewPush,
} from "./review-client";
import styles from "./review.module.css";

const HIDE_KEY = "sx-review-alerts-card";

type Ready = {
  project_id: string;
  app_id: string;
  api_key: string;
  sender_id: string;
};

function ready(config: ReviewPush | null): Ready | null {
  if (!config?.enabled) return null;
  const { project_id, app_id, api_key, sender_id } = config;
  return project_id && app_id && api_key && sender_id
    ? { project_id, app_id, api_key, sender_id }
    : null;
}

export function ReviewAlertsCard() {
  const [offer, setOffer] = useState<Ready | null>(null);
  const [state, setState] = useState<"idle" | "busy" | "off" | "on">("idle");

  useEffect(() => {
    if (!inPhoneApp()) return;
    let alive = true;
    void (async () => {
      const [phone, config] = await Promise.all([
        pushStatus(),
        readReviewPush(),
      ]);
      const settings = ready(config);
      if (!alive || !phone?.supported || !settings) return;
      if (phone.allowed && phone.token) {
        // Already on: this phone gets review alerts, at its current address.
        const app = await phoneStatus();
        void registerReviewPhone(phone.token, app?.version).catch(
          () => undefined,
        );
        return;
      }
      let hidden = false;
      try {
        hidden = localStorage.getItem(HIDE_KEY) === "hidden";
      } catch {
        // Storage blocked: offer it this visit.
      }
      if (!hidden) setOffer(settings);
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (!offer || state === "on") return null;

  const turnOn = async () => {
    setState("busy");
    const phone = await pushEnable(offer);
    if (!phone?.allowed || !phone.token) {
      setState("off");
      return;
    }
    const app = await phoneStatus();
    try {
      await registerReviewPhone(phone.token, app?.version);
      buzz("done");
      setState("on");
    } catch {
      setState("off");
    }
  };

  return (
    <section className={styles.alerts} aria-label="Review alerts">
      <BellRing size={20} aria-hidden="true" />
      <span>
        <strong>Know when a new Report is ready.</strong>{" "}
        {state === "off"
          ? "Alerts are off. Allow notifications for Sales Xray in your phone's settings, then try again."
          : "Get an alert on this phone for each new call to review. Tap it to open the call."}
      </span>
      <button
        type="button"
        className={styles.alertsOn}
        disabled={state === "busy"}
        onClick={() => void turnOn()}
      >
        {state === "busy" ? "Turning on…" : "Turn on alerts"}
      </button>
      <button
        type="button"
        className={styles.alertsClose}
        aria-label="Not now"
        onClick={() => {
          try {
            localStorage.setItem(HIDE_KEY, "hidden");
          } catch {
            // Storage blocked: hidden for this visit only.
          }
          setOffer(null);
        }}
      >
        <X size={16} aria-hidden="true" />
      </button>
    </section>
  );
}
