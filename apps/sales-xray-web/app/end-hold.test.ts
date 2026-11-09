// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// Orchestrator, 9 Nov 2026: at 1440 a focused quick add at the end of the
// Cold list fell 160 px as a corner card left. The content area here works as
// a browser's does: its end room is the shell's rule, max(24px, the card's
// room + 16px, --sx-end-hold), and its scroll can't pass its end, so less
// room pulls the page down.
let keepEndInView: (shrink: () => void) => void;
let main: HTMLElement;
let room: number;
let top: number;
const CONTENT = 3000;
const VIEW = 852;
const held = () =>
  parseFloat(
    document.documentElement.style.getPropertyValue("--sx-end-hold"),
  ) || 0;
const pad = () => Math.max(24, room > 0 ? room + 16 : 0, held());
const height = () => CONTENT + pad();
const scrollTop = () => Math.min(top, height() - VIEW);

beforeEach(async () => {
  vi.resetModules();
  ({ keepEndInView } = await import("./end-hold"));
  document.documentElement.style.removeProperty("--sx-end-hold");
  main = document.createElement("main");
  main.id = "main-content";
  document.body.append(main);
  const style = globalThis.getComputedStyle.bind(globalThis);
  vi.spyOn(globalThis, "getComputedStyle").mockImplementation((node, pseudo) =>
    node === main
      ? ({
          overflowY: "auto",
          paddingBottom: `${pad()}px`,
        } as CSSStyleDeclaration)
      : style(node, pseudo),
  );
  Object.defineProperties(main, {
    scrollHeight: { get: height },
    clientHeight: { get: () => VIEW },
    scrollTop: {
      get: scrollTop,
      set: (value: number) => {
        top = value;
      },
    },
  });
  // The frame comes at once; its id is spent by then.
  vi.stubGlobal("requestAnimationFrame", (ask: FrameRequestCallback) => {
    ask(0);
    return 0;
  });
  // A card in the corner, the page scrolled to its end.
  room = 174;
  top = height() - VIEW;
});
afterEach(() => {
  main.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const scrollUp = (by: number) => {
  top = scrollTop() - by;
  main.dispatchEvent(new Event("scroll"));
};

it("a card leaving with the page at its end leaves what's on screen where it is", () => {
  const before = scrollTop();
  keepEndInView(() => {
    room = 0;
  });
  expect(scrollTop()).toBe(before);
  expect(held()).toBe(190);
});

it("gives the room back as the page scrolls up, only what is below the screen", () => {
  keepEndInView(() => {
    room = 0;
  });
  const end = () => height() - (scrollTop() + VIEW);
  scrollUp(60);
  expect(held()).toBe(130);
  expect(end()).toBe(0);
  scrollUp(60);
  expect(held()).toBe(70);
  scrollUp(200);
  expect(held()).toBe(0);
  expect(document.documentElement.style.getPropertyValue("--sx-end-hold")).toBe(
    "",
  );
  expect(pad()).toBe(24);
});

it("holds nothing when the room that goes was below the screen anyway", () => {
  top = 1000;
  keepEndInView(() => {
    room = 0;
  });
  expect(held()).toBe(0);
  expect(scrollTop()).toBe(1000);
});
