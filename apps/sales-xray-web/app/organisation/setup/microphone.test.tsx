import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MicrophoneAccess } from "./microphone";
vi.mock("../../leads/native-phone", () => ({ inPhoneApp: () => false }));
vi.mock("../../settings/phone-panel", () => ({ PhoneSetupPanel: () => null }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal("isSecureContext", true);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
async function render() {
  await act(async () => root.render(<MicrophoneAccess />));
}
async function tap() {
  await act(async () => {
    host.querySelector("button")!.click();
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
}
it("asks only after a tap and immediately releases the microphone", async () => {
  const stop = vi.fn();
  const get = vi.fn(async () => ({ getTracks: () => [{ stop }] }));
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: get } });
  await render();
  expect(get).not.toHaveBeenCalled();
  await tap();
  expect(get).toHaveBeenCalledWith({ audio: true });
  expect(stop).toHaveBeenCalledOnce();
  expect(host.textContent).toContain("stopped listening");
});
it("explains browser and Windows recovery after denial", async () => {
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: vi.fn(async () => {
        throw new DOMException("blocked", "NotAllowedError");
      }),
    },
  });
  await render();
  await tap();
  expect(host.textContent).toContain("Windows");
  expect(host.textContent).toContain("site’s permissions");
  expect(host.textContent).toContain(
    "Meta approval does not control microphone access",
  );
});
it("does not request browser capture on an insecure origin", async () => {
  vi.stubGlobal("isSecureContext", false);
  const get = vi.fn();
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: get } });
  await render();
  expect(host.querySelector("button")!.disabled).toBe(true);
  expect(host.textContent).toContain("HTTPS");
  expect(get).not.toHaveBeenCalled();
});

it("keeps known blocked access and its Windows recovery steps when capture is unsupported", async () => {
  const get = vi.fn(async () => {
    throw new DOMException("unsupported", "NotSupportedError");
  });
  vi.stubGlobal("navigator", {
    permissions: {
      query: vi.fn(async () => ({
        state: "denied",
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    },
    mediaDevices: { getUserMedia: get },
  });
  await render();
  await tap();
  expect(get).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Windows");
  expect(host.textContent).toContain("site’s permissions");
});
