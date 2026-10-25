// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { VoiceNoteRow } from "./voice-note";

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
