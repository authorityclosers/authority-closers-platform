import { expect, it } from "vitest";

import { folderHint } from "./capture-setup-flow";

// SX-AUTOUPLOAD (25 Nov 2026): sellers picked "Recordings" while the dialer saved to
// "Music/Recordings/Call Recordings", so the folder step names the folder and the two taps.
it("names the folder Android opens and the two taps", () => {
  expect(
    folderHint([{ path: "MIUI/sound_recorder/call_rec", recordings: 12 }]),
  ).toBe(
    "Not yet: Android opens MIUI / sound_recorder / call_rec (12 recordings). Tap Use this folder, then Allow.",
  );
  expect(
    folderHint([
      { path: "Recordings/Call", recordings: 0 },
      { path: "Music/Recordings/Call Recordings", recordings: 1 },
    ]),
  ).toContain("Music / Recordings / Call Recordings (1 recording)");
  expect(folderHint([])).toBe("Not yet: Android opens it for you.");
  expect(folderHint(undefined)).toBe("Not yet: Android opens it for you.");
});
