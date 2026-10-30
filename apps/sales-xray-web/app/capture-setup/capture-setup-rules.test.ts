import { describe, expect, it } from "vitest";

import { parseSetup } from "../leads/native-phone";
import type { CaptureSetup } from "./capture-setup-client";
import {
  isGatedRoute,
  phoneFacts,
  savedWhen,
  setupRequired,
  stepsFor,
} from "./capture-setup-rules";

// Owner, 30 Oct 2026: "simple clicks and disclosure one by one ... kind of
// compulsory before moving into the app ... all our old as well as new users".

const NOW = Date.UTC(2026, 9, 30, 4, 30);
const DEVICE = "install-fictional-1";

const setup = (extra: Partial<CaptureSetup> = {}): CaptureSetup => ({
  schema: "sales-xray-capture-setup/1",
  workspace: "organisation",
  required: true,
  profile_complete: true,
  consent: "on",
  declined_at: null,
  ask_again_at: null,
  phones: [],
  ...extra,
});

const status = (checks: Record<string, boolean>, extra = {}) =>
  parseSetup({
    checks: {
      calls: true,
      notifications: true,
      recordings: true,
      recorder: true,
      battery: true,
      autostart: true,
      ...checks,
    },
    family: "xiaomi",
    model: "Redmi 13",
    autostartNeeded: true,
    version: "1.0.50",
    device: DEVICE,
    folderPickSupported: true,
    folderPicked: true,
    recorderProfile: {
      kind: "folder",
      maker: "xiaomi",
      dialerLabel: "Phone",
      recording: "on",
      folders: [],
      newestMs: NOW - 5 * 60_000,
    },
    ...extra,
  });

const on = { supported: true, on: true, wifiOnly: false };
const ready = phoneFacts(status({}), on)!;

describe("isGatedRoute", () => {
  it("covers Home, Leads and Calls and leaves Settings and Team open", () => {
    for (const path of [
      "/",
      "/dashboard/",
      "/leads",
      "/leads/notes",
      "/prospects/00000000-0000-4000-8000-000000000001",
      "/analysis/calls",
      "/analysis/calls/00000000-0000-4000-8000-000000000001",
    ])
      expect(isGatedRoute(path), path).toBe(true);
    for (const path of [
      "/settings",
      "/settings/privacy",
      "/organisation",
      "/account",
      "/chats",
      null,
    ])
      expect(isGatedRoute(path), String(path)).toBe(false);
  });
});

describe("setupRequired", () => {
  it("holds a seller until name, phone and agreement are in, on the web too", () => {
    expect(setupRequired(setup({ profile_complete: false }), null, NOW)).toBe(
      true,
    );
    expect(setupRequired(setup({ consent: "ask" }), null, NOW)).toBe(true);
    expect(setupRequired(setup({ consent: "off" }), null, NOW)).toBe(true);
    // The web has nothing more to do once both are in.
    expect(setupRequired(setup(), null, NOW)).toBe(false);
  });

  it("holds each phone until it finished, so a fresh install goes through it again", () => {
    expect(setupRequired(setup(), ready, NOW)).toBe(true);
    const finished = setup({
      phones: [
        {
          device: DEVICE,
          model: "Redmi 13",
          app_version: "1.0.50",
          at: new Date(NOW).toISOString(),
          recordings: true,
          background: true,
          uploads: true,
        },
      ],
    });
    expect(setupRequired(finished, ready, NOW)).toBe(false);
    expect(
      setupRequired(finished, { ...ready, device: "install-fresh" }, NOW),
    ).toBe(true);
  });

  it("lets a no stand for a day, then asks again", () => {
    const said = setup({
      consent: "ask",
      declined_at: new Date(NOW).toISOString(),
      ask_again_at: new Date(NOW + 86_400_000).toISOString(),
    });
    expect(setupRequired(said, ready, NOW + 3_600_000)).toBe(false);
    expect(setupRequired(said, ready, NOW + 86_400_001)).toBe(true);
  });

  it("never requires it of Viewers, Finance or a personal workspace", () => {
    expect(
      setupRequired(setup({ required: false, consent: "ask" }), ready, NOW),
    ).toBe(false);
    expect(
      setupRequired(
        setup({
          workspace: "personal",
          required: false,
          consent: "unavailable",
        }),
        ready,
        NOW,
      ),
    ).toBe(false);
  });

  it("asks only for the first two steps in an app too old to upload by itself", () => {
    const old = phoneFacts(status({}), null);
    expect(old?.captureSupported).toBe(false);
    expect(setupRequired(setup(), old, NOW)).toBe(false);
    expect(stepsFor(setup({ consent: "ask" }), old)).toEqual([
      "consent",
      "phone",
    ]);
  });
});

describe("stepsFor", () => {
  it("shows all five steps on a phone that has nothing yet, in the owner's order", () => {
    const fresh = phoneFacts(
      status(
        { notifications: false, battery: false, autostart: false },
        { folderPicked: false },
      ),
      { supported: true, on: false, wifiOnly: true },
    );
    expect(
      stepsFor(setup({ profile_complete: false, consent: "ask" }), fresh),
    ).toEqual([
      "profile",
      "consent",
      "recordings",
      "background",
      "uploads",
      "done",
    ]);
  });

  it("always shows the disclosure, even to someone set up before", () => {
    expect(stepsFor(setup(), ready)).toEqual(["consent", "done"]);
  });

  it("asks for the recorder when the folder is chosen but recording is off", () => {
    const off = phoneFacts(
      status(
        { recorder: false },
        {
          recorderProfile: {
            kind: "folder",
            maker: "xiaomi",
            dialerLabel: "Phone",
            recording: "off",
            folders: [],
          },
        },
      ),
      on,
    )!;
    expect(off.recorderOff).toBe(true);
    expect(stepsFor(setup(), off)).toEqual(["consent", "recordings", "done"]);
  });

  it("ends the web's steps with finishing on the phone", () => {
    expect(
      stepsFor(setup({ profile_complete: false, consent: "ask" }), null),
    ).toEqual(["profile", "consent", "phone"]);
  });

  it("leaves uploads out of a personal workspace, which can't upload by itself", () => {
    const personal = setup({
      workspace: "personal",
      required: false,
      consent: "unavailable",
    });
    const off = phoneFacts(status({}), { ...on, on: false })!;
    expect(stepsFor(personal, off)).toEqual(["consent", "done"]);
    expect(stepsFor(personal, null)).toEqual(["consent"]);
  });
});

describe("savedWhen", () => {
  it("says when the newest recording was saved, in plain words", () => {
    expect(savedWhen(NOW - 20_000, NOW)).toBe("less than a minute ago");
    expect(savedWhen(NOW - 60_000, NOW)).toBe("a minute ago");
    expect(savedWhen(NOW - 12 * 60_000, NOW)).toBe("12 minutes ago");
    expect(savedWhen(NOW - 3 * 3_600_000, NOW)).toBe("3 hours ago");
    expect(savedWhen(Date.UTC(2026, 9, 28, 6), NOW)).toBe("on 28 Oct");
    expect(savedWhen(null, NOW)).toBeNull();
    expect(savedWhen(NOW + 1, NOW)).toBeNull();
  });
});
