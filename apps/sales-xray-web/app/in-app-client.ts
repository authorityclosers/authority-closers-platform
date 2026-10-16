"use client";

import { useSyncExternalStore } from "react";

import { IN_APP_ATTRIBUTE } from "./in-app";

type AppWindow = Window & {
  __sxPhone?: { openCalls?: () => void };
};

function readInApp(): boolean {
  return document.documentElement.hasAttribute(IN_APP_ATTRIBUTE);
}

const subscribeNothing = () => () => {};

/** True inside the phone app. The server render is the website. */
export function useInApp(): boolean {
  return useSyncExternalStore(subscribeNothing, readInApp, () => false);
}

/**
 * The app's own list of calls recorded on the phone, when this build of the
 * app offers it; null on the website and in older builds.
 */
export function phoneCallsOpener(): (() => void) | null {
  if (typeof window === "undefined") return null;
  const open = (window as AppWindow).__sxPhone?.openCalls;
  return typeof open === "function" ? () => open() : null;
}
