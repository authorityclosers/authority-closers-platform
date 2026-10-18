import { expect, it } from "vitest";

import { parseRecorder, parseSetup } from "./native-phone";
import { recorderGuide, recorderSteps } from "./phone-setup-words";

// RecorderProfile.status() on the connected Redmi (Pixel-based Android 13, Google's Phone app), 19 Oct.
const REDMI = {
  dialer: "com.google.android.dialer",
  dialerLabel: "Phone",
  kind: "private",
  maker: "google",
  family: "xiaomi",
  sdk: 33,
  folders: [],
  canRead: true,
  allFiles: false,
  setting: null,
  recording: "private",
  newestMs: null,
  otherDialers: [],
};

const MIUI = {
  dialer: "com.android.contacts",
  dialerLabel: "Phone",
  kind: "folder",
  maker: "xiaomi",
  folders: [
    { path: "MIUI/sound_recorder/call_rec", state: "found", recordings: 12 },
    { path: "Recordings/Call", state: "missing" },
  ],
  recording: "on",
  otherDialers: [
    {
      package: "com.google.android.dialer",
      label: "Phone by Google",
      savesToFolder: false,
    },
  ],
};

it("reads the phone's recorder profile and ignores anything odd", () => {
  expect(parseRecorder(REDMI)).toEqual({
    kind: "private",
    maker: "google",
    dialerLabel: "Phone",
    recording: "private",
    folders: [],
    switchTo: null,
  });
  expect(parseRecorder(MIUI)?.folders).toEqual([
    { path: "MIUI/sound_recorder/call_rec", state: "found", recordings: 12 },
    { path: "Recordings/Call", state: "missing", recordings: 0 },
  ]);
  expect(parseRecorder({ ...REDMI, kind: "magic" })).toBeNull();
  expect(parseRecorder(null)).toBeNull();
  // An older app (before 0.3.40) sends no profile: the checklist still works.
  expect(
    parseSetup({ checks: { recorder: false }, family: "xiaomi" })?.recorder,
  ).toBeNull();
  expect(
    parseSetup({ checks: {}, family: "xiaomi", recorderProfile: REDMI })
      ?.recorder?.kind,
  ).toBe("private");
});

it("says plainly that Google's Phone app keeps recordings to itself", () => {
  const alone = recorderGuide(parseRecorder(REDMI), "xiaomi");
  expect(alone.closed).toBe(true);
  expect(alone.lead).toContain("keeps call recordings inside itself");
  expect(alone.steps.join(" ")).toContain("Calls on this phone, then Record");
  const withMaker = recorderGuide(
    parseRecorder({
      ...REDMI,
      otherDialers: [
        {
          package: "com.android.contacts",
          label: "Xiaomi Phone",
          savesToFolder: true,
        },
      ],
    }),
    "xiaomi",
  );
  expect(withMaker.steps[0]).toBe(
    "Make Xiaomi Phone your Phone app (Settings, Apps, Default apps, Phone app).",
  );
});

it("tells a maker's dialer where its recordings are, or that it's off", () => {
  const on = recorderGuide(parseRecorder(MIUI), "xiaomi");
  expect(on).toEqual({
    lead: "Phone records your calls. 12 found in MIUI/sound_recorder/call_rec.",
    steps: recorderSteps("xiaomi"),
    closed: false,
  });
  expect(
    recorderGuide(parseRecorder({ ...MIUI, recording: "off" }), "xiaomi").lead,
  ).toBe("Call recording is off in Phone.");
  const empty = recorderGuide(
    parseRecorder({
      ...MIUI,
      recording: "unknown",
      folders: [{ path: "Recordings/Call", state: "empty", recordings: 0 }],
    }),
    "samsung",
  );
  expect(empty.lead).toBe("No call recordings yet in Recordings/Call.");
  expect(recorderGuide(null, "samsung")).toEqual({
    lead: null,
    steps: recorderSteps("samsung"),
    closed: false,
  });
});
