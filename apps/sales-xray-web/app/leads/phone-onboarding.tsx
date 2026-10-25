"use client";

/**
 * First run in the Sales X-Ray phone app (owner's phone test, 19 Oct; one
 * guided flow since 24 Oct 2026): once the Terms are accepted, before the
 * app, "Set up this phone" (phone-setup-flow.tsx) asks for what this phone
 * still needs, one screen each, and skips what it already allows. Finishing
 * or closing it marks the phone onboarded, and the Phone setup bar leaves
 * Leads (More and Settings keep every line one tap from its fix). Nothing
 * shows in a browser, in an older app, or to someone who signed in on this
 * phone before.
 */

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { readConsent } from "../consent-renewal-client";
import { FIRST_RUN_ATTRIBUTE } from "../welcome/setup-state";
import { useWorkspaceAccess } from "../workspace-access";
import { callRecorderStatus, inPhoneApp, setupStatus } from "./native-phone";
import { flowSteps } from "./phone-setup-steps";

// "Set up this phone" loads when it opens: most starts never show it.
const PhoneSetupFlow = dynamic(
  () => import("./phone-setup-flow").then((module) => module.PhoneSetupFlow),
  { ssr: false },
);

export const ONBOARDED_KEY = "sx-phone-onboarded";
const CHANGED = "sx-phone-onboarded";
export const PHONE_SETUP_OPEN = "sx-phone-setup-open";

/**
 * Opens "Set up this phone" over whatever page is showing (the More sheet's
 * Phone setup, Settings' Selling). A link to /leads#phone-setup did nothing
 * while Leads was already open (Redmi sweep #2, 24 Oct 2026).
 */
export function openPhoneSetup() {
  window.dispatchEvent(new Event(PHONE_SETUP_OPEN));
}

/** True once this phone went through the first run (or skipped it). */
export function phoneOnboarded(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDED_KEY) !== null;
  } catch {
    return true;
  }
}

function markOnboarded() {
  try {
    window.localStorage.setItem(ONBOARDED_KEY, new Date().toISOString());
  } catch {
    // Private storage off: the first run may show again; nothing breaks.
  }
  window.dispatchEvent(new Event(CHANGED));
}

/** Re-renders when the first run finishes, so the Phone setup bar can leave. */
export function usePhoneOnboarded(): boolean {
  const [done, setDone] = useState(true);
  useEffect(() => {
    const read = () => setDone(phoneOnboarded());
    read();
    window.addEventListener(CHANGED, read);
    return () => window.removeEventListener(CHANGED, read);
  }, []);
  return done;
}

export function PhoneOnboarding() {
  const access = useWorkspaceAccess();
  const signedIn = access?.authenticated === true;
  const [open, setOpen] = useState(false);

  // Asked for from anywhere in the app (openPhoneSetup).
  useEffect(() => {
    const show = () => {
      if (inPhoneApp()) setOpen(true);
    };
    window.addEventListener(PHONE_SETUP_OPEN, show);
    return () => window.removeEventListener(PHONE_SETUP_OPEN, show);
  }, []);

  // Waits for the Terms card (it covers the page while consent isn't
  // current) and for Home's first-run check (where to work, or setup): one
  // flow, one screen at a time (owner, 25 Oct 2026).
  useEffect(() => {
    if (!signedIn || !inPhoneApp() || phoneOnboarded()) return;
    let stopped = false;
    const waiting = () =>
      document.documentElement.hasAttribute("data-sx-consent") ||
      document.documentElement.hasAttribute(FIRST_RUN_ATTRIBUTE);
    const start = async () => {
      if (stopped || phoneOnboarded() || waiting()) return;
      try {
        if ((await readConsent()).status !== "current") return;
      } catch {
        return;
      }
      const status = await setupStatus();
      if (stopped || !status) return; // an app too old to say
      const recorder = await callRecorderStatus();
      if (stopped) return;
      if (!flowSteps(status, recorder).length) {
        markOnboarded();
        return;
      }
      if (waiting()) return;
      setOpen(true);
    };
    void start();
    const watch = new MutationObserver(() => void start());
    watch.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-sx-consent", FIRST_RUN_ATTRIBUTE],
    });
    return () => {
      stopped = true;
      watch.disconnect();
    };
  }, [signedIn]);

  if (!open) return null;
  return (
    <PhoneSetupFlow
      onClose={() => {
        markOnboarded();
        setOpen(false);
      }}
    />
  );
}
