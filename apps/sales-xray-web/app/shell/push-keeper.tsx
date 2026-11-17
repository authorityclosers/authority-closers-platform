"use client";

/**
 * Lead alerts reach every signed-in phone (owner, 17 Nov 2026: Shivam's phone
 * had allowed notifications since 14 Nov, yet only 4 phones in all of
 * production got alerts). The phone's alert address used to reach Sales X-Ray
 * only from the Leads list's alerts card, so an owner or admin who lives on
 * Home never got one. Now the signed-in app sends it after sign-in, on each app
 * start and each workspace, and again when the app comes back to the front
 * with a new address (Android renews it on its own: LeadAlertService keeps the
 * new one for the page). Only where the phone already allows notifications:
 * this never asks (phone setup does, with its purpose).
 */

import { useEffect } from "react";

import { readPushConfig, registerDevice } from "../leads/leads-client";
import {
  inPhoneApp,
  phoneStatus,
  pushEnable,
  pushStatus,
} from "../leads/native-phone";
import { ALERTS_PHONE_ON } from "../settings/notifications-client";

export type KeepResult = "sent" | "same" | "off" | "none";

/** The address this app run last sent, per signed-in workspace. */
const sent = new Map<string, string>();

export function forgetSentPushAddresses() {
  sent.clear();
}

/**
 * Sends this phone's alert address for this account and workspace: always the
 * first time in an app run, after that only when it changed.
 */
export async function keepPushAddress(accountKey: string): Promise<KeepResult> {
  if (!inPhoneApp()) return "none";
  const [phone, config] = await Promise.all([pushStatus(), readPushConfig()]);
  if (!phone?.supported || !phone.allowed || !config?.enabled) return "off";
  const { project_id, app_id, api_key, sender_id } = config;
  if (!project_id || !app_id || !api_key || !sender_id) return "off";
  // Allowed already, so this starts Firebase and reads the address; no ask.
  const token =
    phone.token ??
    (await pushEnable({ project_id, app_id, api_key, sender_id }))?.token ??
    null;
  if (!token) return "off";
  if (sent.get(accountKey) === token) return "same";
  const app = await phoneStatus();
  try {
    await registerDevice(token, app?.version);
  } catch {
    return "off";
  }
  sent.set(accountKey, token);
  window.dispatchEvent(new Event(ALERTS_PHONE_ON));
  return "sent";
}

/** Keeps the phone's alert address current while someone is signed in. */
export function PushKeeper({ accountKey }: { accountKey: string | null }) {
  useEffect(() => {
    if (!accountKey || !inPhoneApp()) return;
    let busy = false;
    const keep = () => {
      if (busy) return;
      busy = true;
      void keepPushAddress(accountKey).finally(() => {
        busy = false;
      });
    };
    keep();
    const onShow = () => {
      if (document.visibilityState === "visible") keep();
    };
    document.addEventListener("visibilitychange", onShow);
    return () => document.removeEventListener("visibilitychange", onShow);
  }, [accountKey]);
  return null;
}
