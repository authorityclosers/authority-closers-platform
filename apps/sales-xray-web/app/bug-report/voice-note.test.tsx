// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// The phone app's bridge, per test (#11): outside the app unless a test says so.
const phone = vi.hoisted(() => ({ inApp: false, version: "" }));
vi.mock("../leads/native-phone", () => ({
  inPhoneApp: () => phone.inApp,
  phoneStatus: async () => (phone.inApp ? { version: phone.version } : null),
}));

import { micRoute, olderThan, VoiceNoteRow } from "./voice-note";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  phone.inApp = false;
});

// Owner, 26 Oct 2026: the microphone is asked for only on a tap, and a refusal offers
// "Allow microphone" and where to turn it on, not a red paragraph.
it("asks for the microphone only on a tap, and offers to ask again", async () => {
  const getUserMedia = vi.fn(async () => {
    throw new DOMException("denied", "NotAllowedError");
  });
  vi.stubGlobal("MediaRecorder", class {});
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  await act(async () =>
    root.render(<VoiceNoteRow note={null} onChange={() => {}} />),
  );
  expect(getUserMedia).not.toHaveBeenCalled();
  const add = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("Add a voice note"),
  );
  await act(async () => add?.click());
  expect(getUserMedia).toHaveBeenCalledTimes(1);
  expect(host.querySelector("[role='alert']")).toBeNull();
  expect(host.textContent).toContain("Voice notes need the microphone");
  const allow = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("Allow microphone"),
  );
  await act(async () => allow?.click());
  expect(getUserMedia).toHaveBeenCalledTimes(2);
});

// #11 (owner, Windows Chrome): where to turn it on is this browser's own route.
it("says where this browser turns the microphone on", () => {
  const chrome =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";
  expect(micRoute(chrome, false)).toContain(
    "Site settings → Microphone → Allow",
  );
  expect(micRoute(`${chrome} Edg/141.0.0.0`, false)).toContain(
    "Permissions for this site",
  );
  expect(
    micRoute(
      "Mozilla/5.0 (Windows NT 10.0; rv:131.0) Gecko/20100101 Firefox/131.0",
      false,
    ),
  ).toContain("microphone icon in the address bar");
  expect(micRoute(chrome, true)).toContain("Apps → Sales X-Ray → Permissions");
});

it("compares app versions", () => {
  expect(olderThan("1.0.34", "1.0.35")).toBe(true);
  expect(olderThan("1.0.35", "1.0.35")).toBe(false);
  expect(olderThan("1.1.0", "1.0.35")).toBe(false);
  expect(olderThan("0.9", "1.0.35")).toBe(true);
});

it("in the Android app before 1.0.35, says an update brings voice notes", async () => {
  Object.assign(phone, { inApp: true, version: "1.0.34" });
  const getUserMedia = vi.fn();
  vi.stubGlobal("MediaRecorder", class {});
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  await act(async () =>
    root.render(<VoiceNoteRow note={null} onChange={() => {}} />),
  );
  const add = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("Add a voice note"),
  );
  await act(async () => add?.click());
  expect(getUserMedia).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Voice notes come in the next app update");
  expect(host.querySelector("[role='alert']")).toBeNull();
});
