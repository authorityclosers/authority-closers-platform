import { describe, expect, it } from "vitest";

import { parseSetup, type SetupStatus } from "../leads/native-phone";
import { permissionItems, putOffKey } from "./permissions-rules";
import {
  captureReady,
  nextStep,
  pendingKeys,
  resumeAt,
  stepOf,
  walkSteps,
  type AskStep,
  type WalkFacts,
} from "./setup-walk-steps";
import {
  batteryLines,
  folderPath,
  phoneWord,
  welcomeLine,
} from "./setup-walk-words";

// Owner, 20 Nov 2026 (style C, "See what to tap"): one ask per screen in the
// study's order, granted screens left out, the dots counting what is left.

const phone = (
  checks: Record<string, boolean>,
  extra: Record<string, unknown> = {},
) =>
  parseSetup({
    checks,
    family: "xiaomi",
    model: "Redmi 13",
    version: "1.0.60",
    device: "install-fictional-1",
    folderPickSupported: true,
    folderPicked: false,
    callLogSupported: true,
    ...extra,
  }) as SetupStatus;

const consent = {
  state: "off" as const,
  words: "Fictional words.",
  version: "v1",
};

function facts(
  status: SetupStatus,
  {
    organisation = true,
    makesCalls = true,
    welcomed = false,
    tested = false,
    privateSeen = false,
    putOff = new Set<string>(),
    skipped = new Set<string>(),
  } = {},
): WalkFacts {
  const items = permissionItems(status, {
    organisation,
    consent: organisation ? consent : null,
  });
  return {
    pending: pendingKeys(items, { putOff, skipped, makesCalls }),
    status,
    makesCalls,
    welcomed,
    tested,
    privateSeen,
  };
}

const NOTHING = {
  calls: false,
  notifications: false,
  callLog: false,
  battery: false,
};
const ALL = { calls: true, notifications: true, callLog: true, battery: true };

describe("walkSteps", () => {
  it("orders a new seller's walk as the study says, with the welcome and the end", () => {
    const status = phone(NOTHING, {
      recorderProfile: { kind: "folder", recording: "on", folders: [] },
    });
    expect(walkSteps(facts(status))).toEqual([
      "welcome",
      "alerts",
      "calls",
      "recordings",
      "battery",
      "analyse",
      "test_call",
      "all_set",
    ]);
  });

  it("leaves out what is granted, and the welcome once seen", () => {
    const status = phone(
      { ...ALL, notifications: false },
      { folderPicked: true },
    );
    expect(walkSteps(facts(status, { welcomed: true }))).toEqual([
      "alerts",
      "analyse",
      "all_set",
    ]);
  });

  it("is one screen with no welcome or end when one thing is left", () => {
    const status = phone(
      { ...ALL, notifications: false },
      { folderPicked: true },
    );
    expect(walkSteps(facts(status, { organisation: false }))).toEqual([
      "alerts",
    ]);
  });

  it("opens nothing when everything is granted, and never for the test call alone", () => {
    const status = phone(ALL, {
      folderPicked: true,
      recorderProfile: { kind: "folder", recording: "on", folders: [] },
    });
    const all = facts(status);
    expect(walkSteps({ ...all, pending: new Set() })).toEqual([]);
  });

  it("asks no call log on the Google Play build", () => {
    const status = phone(
      { ...ALL, callLog: false },
      { folderPicked: true, callLogSupported: false },
    );
    expect(walkSteps(facts(status))).toEqual(["analyse"]);
  });

  it("says once that Google's Phone app keeps recordings private, then leaves it out", () => {
    const status = phone(ALL, {
      recorderProfile: { kind: "private", recording: "private", folders: [] },
    });
    expect(walkSteps(facts(status, { welcomed: true }))).toEqual([
      "recordings",
      "analyse",
      "all_set",
    ]);
    expect(
      walkSteps(facts(status, { welcomed: true, privateSeen: true })),
    ).toEqual(["analyse"]);
  });

  it("gives someone who makes no calls on this phone alerts and the consent only", () => {
    const status = phone(NOTHING, {
      recorderProfile: { kind: "folder", recording: "on", folders: [] },
    });
    expect(walkSteps(facts(status, { makesCalls: false }))).toEqual([
      "welcome",
      "alerts",
      "analyse",
      "all_set",
    ]);
  });

  it("opens at one screen when asked for one, and not at all when it is done", () => {
    const status = phone(ALL, { folderPicked: true });
    expect(walkSteps(facts(status), "analyse")).toEqual(["analyse"]);
    expect(walkSteps(facts(status), "alerts")).toEqual([]);
  });

  it("skips what was put off, the needed rows only for this open", () => {
    const status = phone(
      { ...ALL, calls: false, callLog: false },
      { folderPicked: true },
    );
    const items = permissionItems(status, { organisation: true });
    const callLog = items.find((item) => item.key === "callLog")!;
    const phoneRow = items.find((item) => item.key === "phone")!;
    // Call log can wait: put off on this phone. Phone is needed: put off for this open.
    expect([
      ...pendingKeys(items, {
        putOff: new Set([putOffKey(callLog), putOffKey(phoneRow)]),
        skipped: new Set(),
        makesCalls: true,
      }),
    ]).toEqual(["phone"]);
    expect([
      ...pendingKeys(items, {
        putOff: new Set([putOffKey(callLog)]),
        skipped: new Set([putOffKey(phoneRow)]),
        makesCalls: true,
      }),
    ]).toEqual([]);
  });

  it("names the screen that answers each row", () => {
    expect(stepOf("contacts")).toBe("calls");
    expect(stepOf("autoAnalysis")).toBe("analyse");
    expect(stepOf("notifications")).toBe("alerts");
  });
});

describe("nextStep and resumeAt", () => {
  const steps = ["welcome", "alerts", "calls", "battery", "all_set"] as const;
  const open =
    (...keys: AskStep[]) =>
    (step: AskStep) =>
      keys.includes(step);

  it("moves to the next screen still open, and past the end to nothing", () => {
    expect(nextStep(steps, "welcome", open("alerts", "battery"))).toBe(
      "alerts",
    );
    expect(nextStep(steps, "alerts", open("battery"))).toBe("battery");
    expect(nextStep(steps, "alerts", open())).toBe("all_set");
    expect(nextStep(steps, "all_set", open())).toBeNull();
  });

  it("starts at the top, or after a closed app at the first screen still open", () => {
    expect(resumeAt(steps, null, open("calls"))).toBe("welcome");
    expect(resumeAt(steps, "calls", open("calls", "battery"))).toBe("calls");
    expect(resumeAt(steps, "alerts", open("battery"))).toBe("battery");
    expect(resumeAt(["alerts"], null, open())).toBeNull();
  });
});

describe("captureReady", () => {
  it("needs calls and the recordings folder on a phone whose dialler saves files", () => {
    const profile = { kind: "folder", recording: "on", folders: [] };
    expect(
      captureReady(
        phone(ALL, { folderPicked: true, recorderProfile: profile }),
      ),
    ).toBe(true);
    expect(captureReady(phone(ALL, { recorderProfile: profile }))).toBe(false);
    expect(captureReady(phone(ALL, { folderPicked: true }))).toBe(false);
  });
});

describe("setup-walk-words", () => {
  it("names the phone and its recordings folder, the real one first", () => {
    const status = phone(ALL, {
      recorderProfile: {
        kind: "folder",
        recording: "on",
        folders: [
          {
            path: "/storage/emulated/0/Recordings/Call",
            state: "found",
            recordings: 2,
          },
        ],
      },
    });
    expect(phoneWord(status)).toBe("Redmi");
    expect(folderPath(status)).toEqual(["Recordings", "Call"]);
    expect(folderPath(phone(ALL))).toEqual([
      "MIUI",
      "sound_recorder",
      "call_rec",
    ]);
    expect(folderPath(phone(ALL, { family: "other" }))).toEqual([]);
  });

  it("names the maker's battery page, and Autostart only where it is needed", () => {
    expect(batteryLines(phone(ALL, { autostartNeeded: true }))).toEqual([
      { page: "Battery saver", choose: "No restrictions" },
      { page: "Autostart", choose: "On" },
    ]);
    expect(batteryLines(phone(ALL, { family: "samsung" }))).toEqual([
      { page: "Battery", choose: "Unrestricted" },
    ]);
  });

  it("counts the welcome's steps and minutes", () => {
    expect(welcomeLine(6)).toBe(
      "6 quick steps so every sales call gets checked. About 2 minutes.",
    );
    expect(welcomeLine(2)).toBe(
      "2 quick steps so every sales call gets checked. About 1 minute.",
    );
  });
});
