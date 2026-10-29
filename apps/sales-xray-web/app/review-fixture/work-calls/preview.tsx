"use client";

/**
 * Leads' "Log work calls by themselves" card with a fictional phone app, for
 * the Play call-log declaration review. In Personal (the default) the phone
 * refuses as PhoneBridge does, with organisation_required and no Android
 * prompt, and Turn on is pressed once so the card's answer shows.
 * ?workspace=company: the phone takes it and the slim row shows. Nothing is
 * asked of Android and nothing is sent.
 */
import { useEffect, useState, useSyncExternalStore } from "react";

import { PhoneLogCard } from "../../leads/phone-log-card";
import styles from "./preview.module.css";

const noSubscription = () => () => {};
const browser = () => true;

const company = () =>
  new URLSearchParams(window.location.search).get("workspace") === "company";

function install() {
  if (typeof window === "undefined") return;
  let on = false;
  const listeners = new Set<(event: { data: string }) => void>();
  const status = () => ({
    on,
    access: true,
    sims: [{ id: "fictional-sim", label: "Work SIM" }],
    sim: "fictional-sim",
    lastSyncMs: on ? Date.now() - 120_000 : null,
    lastLogged: 0,
    state: on ? "ok" : "never",
  });
  Object.assign(window, {
    SXPhone: {
      addEventListener: (
        _type: string,
        listener: (event: { data: string }) => void,
      ) => listeners.add(listener),
      postMessage: (data: string) => {
        const request = JSON.parse(data) as {
          id: string;
          method: string;
          args: { on?: boolean };
        };
        const refuse = request.method === "callLogSetup" && !company();
        if (request.method === "callLogSetup" && !refuse)
          on = request.args.on === true;
        const reply = refuse
          ? { id: request.id, ok: false, error: "organisation_required" }
          : { id: request.id, ok: true, result: status() };
        setTimeout(() => {
          for (const listener of listeners)
            listener({ data: JSON.stringify(reply) });
        }, 0);
      },
    },
  });
}

export function WorkCallsPreview() {
  useState(install);
  const mounted = useSyncExternalStore(noSubscription, browser, () => false);

  // Personal: press Turn on once, as the seller would.
  useEffect(() => {
    if (!mounted || company()) return;
    let tries = 0;
    const timer = window.setInterval(() => {
      const turnOn = [...document.querySelectorAll("button")].find(
        (item) => item.textContent === "Turn on",
      );
      if (turnOn) turnOn.click();
      if (turnOn || ++tries > 40) window.clearInterval(timer);
    }, 50);
    return () => window.clearInterval(timer);
  }, [mounted]);

  if (!mounted) return null;
  return (
    <main className={styles.page}>
      <h1>{company() ? "Example Sales" : "Personal"} · Leads</h1>
      <PhoneLogCard />
    </main>
  );
}
