/**
 * The words of phone setup's one-ask screens (work/SCREEN-SPEC.md, 20 Nov
 * 2026), and the lines that change with the phone's maker (STUDY.md §3): the
 * recordings folder's path, and what the battery and Autostart settings are
 * called. The consent's words are never here: they come sealed from the
 * server and are shown as they are.
 */

import type { SetupStatus } from "../leads/native-phone";
import type { AskStep } from "./setup-walk-steps";

/**
 * A number of our own for the test call, when the organisation has one (owner
 * to give; none yet, 20 Nov 2026). Empty: the seller calls anyone they like,
 * as capture setup's test call already does.
 */
export const TEST_CALL_NUMBER = "";

/** How long the test call should last. */
export const TEST_CALL_SECONDS = 20;

const BRAND: Readonly<Record<string, string>> = {
  xiaomi: "Xiaomi",
  samsung: "Samsung",
  oppo: "Oppo",
  realme: "Realme",
  vivo: "Vivo",
  oneplus: "OnePlus",
  huawei: "Huawei",
};

/** The phone's own word in a sentence: "Redmi" for a Redmi 13, else its maker, else "phone". */
export function phoneWord(
  status: Pick<SetupStatus, "model" | "family">,
): string {
  const first = status.model.trim().split(/\s+/)[0] ?? "";
  return /^(redmi|poco|galaxy|pixel|oneplus|nord|iqoo|realme|vivo|oppo)$/i.test(
    first,
  )
    ? first.charAt(0).toUpperCase() + first.slice(1)
    : (BRAND[status.family] ?? "phone");
}

/**
 * Where the built-in recorder saves calls, by maker (STUDY.md §3; Xiaomi's is
 * Xiaomi's own help page, the others still to check on a phone).
 */
const FOLDER_BY_FAMILY: Readonly<Record<string, readonly string[]>> = {
  xiaomi: ["MIUI", "sound_recorder", "call_rec"],
  samsung: ["Recordings", "Call"],
  oppo: ["Music", "Recordings", "Call Recordings"],
  realme: ["Music", "Recordings", "Call Recordings"],
  vivo: ["Record", "Call"],
};

/**
 * The recordings folder as the picker shows it, at most three folders deep:
 * the folder this phone's recorder really uses when the app found it, else
 * the maker's usual one. Empty when neither is known.
 */
export function folderPath(status: SetupStatus): string[] {
  const found = [...(status.recorder?.folders ?? [])].sort(
    (a, b) => b.recordings - a.recordings,
  )[0]?.path;
  if (found) {
    const parts = found
      .replace(/^\/?storage\/emulated\/\d+\/?/, "")
      .replace(/^\/?sdcard\/?/, "")
      .split("/")
      .filter(Boolean);
    if (parts.length) return parts.slice(-3);
  }
  return [...(FOLDER_BY_FAMILY[status.family] ?? [])];
}

export type BatteryLine = Readonly<{ page: string; choose: string }>;

/** Battery first, then Autostart where this maker stops apps without it. */
export function batteryLines(status: SetupStatus): BatteryLine[] {
  const family = status.family;
  const battery: BatteryLine =
    family === "xiaomi"
      ? { page: "Battery saver", choose: "No restrictions" }
      : family === "oppo" || family === "realme"
        ? { page: "Battery usage", choose: "Allow background activity" }
        : family === "vivo"
          ? { page: "Background power consumption", choose: "Allow" }
          : { page: "Battery", choose: "Unrestricted" };
  if (!status.autostartNeeded) return [battery];
  const autostart: BatteryLine =
    family === "oppo" || family === "realme" || family === "oneplus"
      ? { page: "Auto launch", choose: "On" }
      : { page: "Autostart", choose: "On" };
  return [battery, autostart];
}

export type StepWords = Readonly<{
  title: string;
  line: string;
  /** A second, smaller line under the sentence. */
  note?: string;
  action: string;
  /** The quiet button: Not now, or Skip for the optional test call. */
  later: string;
}>;

/** The welcome's sentence: how many screens, and about how long. */
export function welcomeLine(count: number): string {
  const minutes = Math.max(1, Math.round(count / 3));
  return `${count} quick ${count === 1 ? "step" : "steps"} so every sales call gets checked. About ${minutes} ${minutes === 1 ? "minute" : "minutes"}.`;
}

export const WELCOME: StepWords = {
  title: "Let's set up your phone",
  line: welcomeLine(6),
  action: "Start",
  later: "I don't make calls on this phone",
};

export const ALL_SET: StepWords = {
  title: "You're ready",
  line: "Your next sales call will be checked automatically.",
  action: "Go to Home",
  later: "",
};

/** The end of a walk with something put off: honest, and where to finish. */
export const ALMOST_SET: StepWords = {
  title: "Almost ready",
  line: "Finish the rest any time from Settings, Phone setup.",
  action: "Go to Home",
  later: "",
};

/** What each one-ask screen says, for this phone and what is left to ask. */
export function stepWords(
  step: AskStep,
  status: SetupStatus,
  {
    settings = false,
    dialogs = 2,
    phase = "battery",
    test = "ready",
  }: {
    /** Android won't ask again: the button opens its settings. */
    settings?: boolean;
    /** How many questions Android will show on the calls screen. */
    dialogs?: number;
    /** Battery first, then Autostart. */
    phase?: "battery" | "autostart";
    /** The test call: not placed yet, waiting for its recording, or none found. */
    test?: "ready" | "waiting" | "missing";
  } = {},
): StepWords {
  switch (step) {
    case "alerts":
      return settings
        ? {
            title: "Hear about new leads first",
            line: "Android won't ask again here. Open settings and switch on notifications for Sales X-Ray.",
            action: "Open settings",
            later: "Not now",
          }
        : {
            title: "Hear about new leads first",
            line: "We'll alert you the moment a lead comes in or a call is due.",
            action: "Allow alerts",
            later: "Not now",
          };
    case "calls":
      return settings
        ? {
            title: "Let Sales X-Ray see your work calls",
            line: "Android won't ask again here. Open settings, then Permissions, and allow Phone and Call logs.",
            note: "Only calls with your leads are logged. Other numbers stay on your phone.",
            action: "Open settings",
            later: "Not now",
          }
        : {
            title: "Let Sales X-Ray see your work calls",
            line:
              dialogs <= 1
                ? "Your phone will ask once. Tap Allow."
                : dialogs === 2
                  ? "Your phone will ask twice. Tap Allow both times."
                  : "Your phone will ask a few times. Tap Allow each time.",
            note: "Only calls with your leads are logged. Other numbers stay on your phone.",
            action: "Continue",
            later: "Not now",
          };
    case "recordings": {
      if (status.recorder?.kind === "private")
        return {
          title: "Your Phone app keeps recordings private",
          line: `${status.recorder.dialerLabel || "Google's Phone app"} doesn't share its call recordings with other apps, so there's no folder to choose on this phone.`,
          action: "Got it",
          later: "Not now",
        };
      const path = folderPath(status);
      return {
        title: "Show us where your calls are saved",
        line: path.length
          ? `On your ${phoneWord(status)}, choose: ${path.join(" › ")}, then tap Use this folder.`
          : "Choose the folder your Phone app saves call recordings in, then tap Use this folder.",
        action: "Choose folder",
        later: "Not now",
      };
    }
    case "battery": {
      const lines = batteryLines(status);
      // The numbered lines themselves are batteryLines(), listed on the screen.
      return {
        title: "Keep uploads running in the background",
        line: "",
        action:
          phase === "autostart" && lines[1]
            ? `Open ${lines[1].page}`
            : "Open settings",
        later: "Not now",
      };
    }
    case "analyse":
      return {
        title: "Analyse my calls automatically?",
        line: "",
        action: "Turn on",
        later: "Not now",
      };
    case "test_call":
      return {
        title: `Try a ${TEST_CALL_SECONDS}-second test call`,
        line:
          test === "waiting"
            ? "Looking for your test call's recording…"
            : test === "missing"
              ? "No recording arrived yet. Check your Phone app records all calls, then try again."
              : TEST_CALL_NUMBER
                ? "Call our free test number, hang up, and see your call arrive."
                : `Call anyone for ${TEST_CALL_SECONDS} seconds (a friend, or your own voicemail), hang up, and see your call arrive.`,
        action: test === "missing" ? "Try again" : "Make a test call",
        later: "Skip",
      };
  }
}
