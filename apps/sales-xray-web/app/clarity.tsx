"use client";

/**
 * Microsoft Clarity: session replays and heatmaps (owner, 28 Oct 2026, "get that
 * done"; the usage analytics notice v3). Its tag loads only when the server says
 * it records this person, signed in with usage analytics on and never in a
 * sandbox, and only where the environment has a Clarity project (production, from
 * its release profile). Otherwise no request ever goes to Clarity.
 * - The project masks all text (Strict), and the page body carries
 *   data-clarity-mask (layout.tsx), so leads, calls, reports, transcripts and
 *   chats stay masked whatever the project's setting.
 * - Nothing tells Clarity who anyone is: no identify call, no custom tags.
 *   Advertising storage is denied, so no Microsoft Advertising cookie is set.
 * - The Android app's WebView shows this same page, so the same rule holds
 *   there; there is no native SDK.
 */

import { useEffect } from "react";

import { telemetry } from "./telemetry";

type ClarityQueue = ((...args: unknown[]) => void) & { q?: unknown[][] };

const PROJECT = /^[a-z0-9]{6,32}$/;
let started = false;

/** Clarity's tag for this project, once a page (Microsoft's own snippet, as code). */
export function startClarity(project: string) {
  if (started || typeof window === "undefined" || !PROJECT.test(project))
    return;
  started = true;
  const host = window as typeof window & { clarity?: ClarityQueue };
  const queue: ClarityQueue =
    host.clarity ??
    ((...args: unknown[]) => {
      (queue.q ??= []).push(args);
    });
  host.clarity = queue;
  queue("consentv2", { ad_Storage: "denied", analytics_Storage: "granted" });
  const script = document.createElement("script");
  script.async = true;
  script.src = `https://www.clarity.ms/tag/${project}`;
  document.head.appendChild(script);
}

/** Loads Clarity when, and only when, telemetry's server answer allows it. */
export function ClarityGate() {
  useEffect(() => telemetry.whenReplay(startClarity), []);
  return null;
}

/** Tests only: forget that the tag was added. */
export function resetClarityForTest() {
  started = false;
}
