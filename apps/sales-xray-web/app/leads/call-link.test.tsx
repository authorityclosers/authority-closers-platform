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
  // Enter on the focused link, or TalkBack's double tap: a click, no touch.
  await act(async () => link().click());
  expect(calls).toEqual(["pointerup", "click"]);
  expect(pressed.report).toHaveBeenCalledWith("click");
});
