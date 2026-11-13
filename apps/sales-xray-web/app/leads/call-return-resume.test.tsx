// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const phone = vi.hoisted(() => ({ app: true }));
vi.mock("./native-phone", async (original) => ({
  ...(await original<typeof import("./native-phone")>()),
  inPhoneApp: () => phone.app,
  // The phone couldn't say how the call ended (call history off).
  readLastCall: async () => null,
  onPhoneCall: () => () => undefined,
}));

import { rememberCall } from "./leads-client";
import { rememberAppCall, useCallReturn, usePhoneAppCall } from "./lead-sheet";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  localStorage.clear();
});

// The phone app's "back in front" signal, as sx-phone.js sends it.
const resume = () =>
  window.dispatchEvent(
    new CustomEvent("sx-phone", { detail: { event: "resume" } }),
  );

function Watch({
  onReturn,
  onBack,
}: {
  onReturn: (seconds: number) => void;
  onBack: () => void;
}) {
  useCallReturn("lead-1", onReturn);
  usePhoneAppCall("lead-1", () => undefined, onBack);
  return null;
}

// Redmi QA batch 12 (13 Nov 2026, production): back from a real call in the
// phone app, the lead page showed nothing, no question and no "Back from
// calling", and didn't refresh. Its WebView didn't say it was shown again; the
// app's own resume signal now does.
it("follows a call when the phone app says it is back in front", async () => {
  const onReturn = vi.fn();
  const onBack = vi.fn();
  await act(async () =>
    root.render(<Watch onReturn={onReturn} onBack={onBack} />),
  );
  expect(onReturn).not.toHaveBeenCalled();
  expect(onBack).not.toHaveBeenCalled();
  // The Call was tapped ten seconds ago; the page never saw itself hidden.
  rememberCall("lead-1", Date.now() - 10_000);
  rememberAppCall("lead-1", Date.now() - 10_000);
  await act(async () => resume());
  expect(onReturn).toHaveBeenCalledTimes(1);
  expect(onReturn.mock.calls[0][0]).toBeGreaterThanOrEqual(10);
  expect(onBack).toHaveBeenCalledTimes(1);
  // Once: another resume asks nothing more.
  await act(async () => resume());
  expect(onReturn).toHaveBeenCalledTimes(1);
  expect(onBack).toHaveBeenCalledTimes(1);
});
