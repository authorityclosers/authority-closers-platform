// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const phone = vi.hoisted(() => ({ inApp: false }));
vi.mock("./native-phone", () => ({ inPhoneApp: () => phone.inApp }));

import {
  IN_APP_CALL,
  IN_APP_CALL_HINT,
  InAppCallHint,
  useInPhoneApp,
} from "./call-hint";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  phone.inApp = false;
});

function CallButton() {
  const inApp = useInPhoneApp();
  return (
    <>
      <button type="button">{inApp ? IN_APP_CALL : "Call"}</button>
      <InAppCallHint />
    </>
  );
}

it("says why to call from here, inside the phone app", () => {
  phone.inApp = true;
  act(() => root.render(<CallButton />));
  expect(container.querySelector("button")?.textContent).toBe(
    "Call from Sales X-Ray",
  );
  const hint = container.querySelector("[data-call-hint]");
  expect(hint?.textContent).toBe(IN_APP_CALL_HINT);
});

it("says nothing more in a browser, where the call goes to the dialler", () => {
  act(() => root.render(<CallButton />));
  expect(container.querySelector("button")?.textContent).toBe("Call");
  expect(container.querySelector("[data-call-hint]")).toBeNull();
});
