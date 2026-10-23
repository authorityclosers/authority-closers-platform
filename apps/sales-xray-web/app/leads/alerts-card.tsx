"use client";

/**
 * Lead alerts on the phone (UX study item 4): inside the Sales Xray Android
 * app, a one-time card asks to turn on alerts for a new lead or a call that is
 * due. After that the phone's alert address is re-sent quietly each visit, so
 * a renewed address keeps working. Nothing shows in a browser, in an older app
 * or while alerts aren't set up on this server.
 */

import { BellRing, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "../ui/kit";
import {
  readPushConfig,
  registerDevice,
  type PushConfig,
} from "./leads-client";
import {
  buzz,
  inPhoneApp,
  phoneStatus,
  pushEnable,
  pushStatus,
} from "./native-phone";
import styles from "./leads.module.css";

const HIDE_KEY = "sx-leads-alerts-card";

type Ready = {
  project_id: string;
  app_id: string;
  api_key: string;
  sender_id: string;
};

function ready(config: PushConfig | null): Ready | null {
  if (!config?.enabled) return null;
  const { project_id, app_id, api_key, sender_id } = config;
  return project_id && app_id && api_key && sender_id
    ? { project_id, app_id, api_key, sender_id }
    : null;
}

export function AlertsCard() {
  const [offer, setOffer] = useState<Ready | null>(null);
  const [state, setState] = useState<"idle" | "busy" | "off" | "on">("idle");

  useEffect(() => {
    if (!inPhoneApp()) return;
    let alive = true;
    void (async () => {
      const [phone, config] = await Promise.all([
        pushStatus(),
        readPushConfig(),
      ]);
      const settings = ready(config);
      if (!alive || !phone?.supported || !settings) return;
      if (phone.allowed && phone.token) {
        // Already on: keep this phone's address current on the server.
        const app = await phoneStatus();
        void registerDevice(phone.token, app?.version).catch(() => undefined);
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
      await registerDevice(phone.token, app?.version);
      buzz("done");
      setState("on");
    } catch {
      setState("off");
    }
  };

  return (
    <section className={styles.alertsCard} aria-label="Lead alerts">
      <BellRing size={20} aria-hidden="true" />
      <span>
        <strong>Know the moment a lead comes in.</strong>{" "}
        {state === "off"
          ? "Alerts are off. Allow notifications for Sales X-Ray in your phone's settings, then try again."
          : "Get an alert for a new lead or a call that is due. Tap it to open the lead."}
      </span>
      <Button
        variant="primary"
        className={styles.bannerAction}
        disabled={state === "busy"}
        onClick={() => void turnOn()}
      >
        {state === "busy" ? "Turning on…" : "Turn on alerts"}
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
          setOffer(null);
        }}
      >
        <X size={16} aria-hidden="true" />
      </button>
    </section>
  );
}
