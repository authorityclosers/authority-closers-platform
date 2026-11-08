// Bug report #164 (owner's OnePlus, 3 Nov 2026): "Fix recording" was slow to
// open, then said this version can't record, "download from Play Store", on
// the app installed from Google Play.
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  captureForSetup,
  forgetCaptureForSetup,
  parseSetup,
} from "../leads/native-phone";
import { phoneStepWords } from "./capture-setup-flow";
import { failingStep, phoneFacts } from "./capture-setup-rules";

type Listener = (event: { data: unknown }) => void;

/** The phone app, answering autoCaptureStatus as told (or never). */
function fakePhone(
  answer: "ok" | "unknown_method" | "capture_unavailable" | "never",
) {
  const listeners: Listener[] = [];
  const asked: string[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as { id: string; method: string };
      asked.push(message.method);
      if (answer === "never") return;
      const reply =
        answer === "ok"
          ? {
              id: message.id,
              ok: true,
              result: { supported: true, on: true, wifiOnly: false },
            }
          : { id: message.id, ok: false, error: answer };
      queueMicrotask(() =>
        listeners.forEach((listener) =>
          listener({ data: JSON.stringify(reply) }),
        ),
      );
    },
  });
  return asked;
}

const playStatus = parseSetup({
  checks: {
    calls: true,
    notifications: true,
    recordings: true,
    recorder: true,
    battery: true,
  },
  family: "oneplus",
  model: "OnePlus 12",
  version: "1.0.87",
  device: "install-fictional-164",
  folderPickSupported: true,
  folderPicked: true,
  store: "play",
  recorderProfile: {
    kind: "folder",
    maker: "oneplus",
    recording: "on",
    folders: [],
  },
});

afterEach(() => {
  forgetCaptureForSetup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the call setup's reading of automatic uploads (#164)", () => {
  it("a phone slow to answer is an app with uploads, never an app to update", async () => {
    vi.useFakeTimers();
    fakePhone("never");
    const read = captureForSetup();
    await vi.advanceTimersByTimeAsync(5_001);
    const capture = await read;
    expect(capture).toMatchObject({ supported: true, unanswered: true });
    const facts = phoneFacts(playStatus, capture);
    expect(facts?.captureSupported).toBe(true);
    // Uploads unknown are not sent to the uploads step either.
    expect(facts?.uploadsOn).toBe(true);
    expect(failingStep(facts)).not.toBe("phone");
  });

  it("an app that couldn't reach the server for its phone book still has uploads", async () => {
    fakePhone("capture_unavailable");
    const capture = await captureForSetup();
    expect(phoneFacts(playStatus, capture)?.captureSupported).toBe(true);
  });

  it("only an app without the method is too old", async () => {
    fakePhone("unknown_method");
    const capture = await captureForSetup();
    expect(capture).toBeNull();
    expect(failingStep(phoneFacts(playStatus, capture))).toBe("phone");
  });

  it("Fix recording and the setup it opens ask the phone once", async () => {
    const asked = fakePhone("ok");
    const first = await captureForSetup();
    const second = await captureForSetup();
    expect(second).toBe(first);
    expect(
      asked.filter((method) => method === "autoCaptureStatus"),
    ).toHaveLength(1);
    forgetCaptureForSetup();
    await captureForSetup();
    expect(
      asked.filter((method) => method === "autoCaptureStatus"),
    ).toHaveLength(2);
  });
});

describe("the phone step's words (#164)", () => {
  it("never tells a phone that didn't answer to update from Google Play", () => {
    const words = phoneStepWords(true, null);
    expect(words.play).toBeNull();
    expect(`${words.title} ${words.line}`).not.toMatch(/Google Play|Update/);
  });

  it("an Android too old to pick a folder is not told to update the app", () => {
    const old = parseSetup({
      checks: {},
      version: "1.0.87",
      folderPickSupported: false,
    });
    const words = phoneStepWords(true, old);
    expect(words.play).toBeNull();
    expect(words.line).not.toMatch(/Google Play/);
  });

  it("an app really too old still says update; the web says finish on the phone", () => {
    expect(phoneStepWords(true, playStatus).title).toBe("Update Sales X-Ray");
    expect(phoneStepWords(false, null).title).toBe("Now finish on your phone");
  });
});
