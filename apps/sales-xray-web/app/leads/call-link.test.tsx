// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const pressed = vi.hoisted(() => ({ report: vi.fn() }));
vi.mock("./phone-call-steps", () => ({ reportCallPress: pressed.report }));

import { CallLink } from "./call-link";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let calls: string[];

beforeEach(async () => {
  calls = [];
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <CallLink
        phone="+910000000000"
        className="call"
        aria-busy={undefined}
        onCall={(event) => {
          event.preventDefault();
          calls.push(event.type);
        }}
      >
        Call
      </CallLink>,
    ),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

const link = () => host.querySelector<HTMLAnchorElement>("a")!;

/** The page hides (the dialer opened), then shows again. */
function hidePage() {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: true,
  });
  document.dispatchEvent(new Event("visibilitychange"));
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
}

it("is the lead's tel: link, marked so a touch on it isn't timed as a call", () => {
  expect(link().getAttribute("href")).toBe("tel:+910000000000");
  expect(link().hasAttribute("data-sx-call")).toBe(true);
  expect(link().className).toBe("call");
});

it("calls on a touch whose click a glide ate, and on a keyboard or screen reader's click", async () => {
  const touch = (type: string) =>
    link().dispatchEvent(
      new PointerEvent(type, {
        bubbles: true,
        cancelable: true,
        pointerType: "touch",
        isPrimary: true,
        pointerId: 5,
      }),
    );
  await act(async () => {
    touch("pointerdown");
    touch("pointerup");
  });
  expect(calls).toEqual(["pointerup"]);
  expect(pressed.report).toHaveBeenCalledWith("touch");
  await act(async () => {
    await new Promise((done) => setTimeout(done, 850));
  });
  // The dialer opened and the page hid; back on it, a new press calls again.
  hidePage();
  // Enter on the focused link, or TalkBack's double tap: a click, no touch.
  await act(async () => link().click());
  expect(calls).toEqual(["pointerup", "click"]);
  expect(pressed.report).toHaveBeenCalledWith("click");
  hidePage();
});

// Leads part 04: no double dial. A second tap on the same number within 2.5 s is
// the same call, until the page hides (the dialer opened).
it("never dials twice for a double tap, and calls again once the dialer opened", async () => {
  const touch = (type: string) =>
    link().dispatchEvent(
      new PointerEvent(type, {
        bubbles: true,
        cancelable: true,
        pointerType: "touch",
        isPrimary: true,
        pointerId: 7,
      }),
    );
  const tap = () =>
    act(async () => {
      touch("pointerdown");
      touch("pointerup");
    });
  await tap();
  await tap();
  expect(calls).toEqual(["pointerup"]);
  hidePage();
  await tap();
  expect(calls).toEqual(["pointerup", "pointerup"]);
  hidePage();
});
