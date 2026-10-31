import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.fn();
vi.mock("../notice-center", () => ({
  notify: (...args: unknown[]) => notify(...args),
}));
vi.mock("./capture", () => ({ captureScreen: async () => null }));
vi.mock("./device", () => ({
  reportContext: async () => ({
    app: { channel: "web", release: "abc123" },
    device: { os: "Android 14", viewport: "390x844" },
  }),
}));
vi.mock("./outbox", () => ({ keepNow: async () => false }));

import { resetBackCloseForTests } from "../ui/back-close";
import {
  AdvancedReporter,
  wordsWithComments,
  type AdvancedSeed,
} from "./advanced-reporter";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// A screen that can show calls: no picture is taken, so none is waited for.
const seed: AdvancedSeed = {
  words: "The stage chip did not change",
  blocksWork: false,
  about: null,
  picture: null,
  source: "auto",
  sensitive: true,
};

let root: Root;
let host: HTMLDivElement;
const onClose = vi.fn();
const onSent = vi.fn();

beforeEach(async () => {
  notify.mockReset();
  onClose.mockReset();
  onSent.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <AdvancedReporter open seed={seed} onClose={onClose} onSent={onSent} />,
    ),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

const words = () =>
  document.querySelector<HTMLTextAreaElement>(
    'textarea[placeholder^="What did you do"]',
  )!;

async function type(area: HTMLTextAreaElement, text: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )!.set!;
  await act(async () => {
    setter.call(area, text);
    area.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const cancel = () =>
  act(async () => {
    document
      .querySelector("dialog")!
      .dispatchEvent(new Event("cancel", { cancelable: true }));
  });

const button = (name: string) =>
  [...document.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === name,
  )!;

it("starts from what the basic reporter had, and asks before anything is lost", async () => {
  expect(document.querySelector("dialog h2")?.textContent).toBe(
    "Report a problem",
  );
  expect(words().value).toBe(seed.words);
  expect(document.body.textContent).toContain("so no picture is taken");
  // Nothing new: Esc closes straight away.
  await cancel();
  expect(onClose).toHaveBeenCalledTimes(1);
  // Something new: Esc asks first.
  await type(words(), `${seed.words} after I picked Interested.`);
  await cancel();
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).toContain("Discard this report?");
  await act(async () => button("Keep editing").click());
  expect(document.body.textContent).not.toContain("Discard this report?");
});

it("sends with Ctrl Enter after asking once, then without asking", async () => {
  window.localStorage.removeItem("sx-bug-report-keys-send");
  const fetcher = vi.fn(async (path: string) =>
    path === "/v1/bug-reports"
      ? new Response(
          JSON.stringify({
            bug_id: "bug-1",
            screenshot: "none",
            voice: "none",
          }),
          { status: 201 },
        )
      : new Response("{}", { status: 404 }),
  );
  vi.stubGlobal("fetch", fetcher);
  await type(words(), "The stage chip did not change after Interested.");
  await act(async () => {
    words().dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        ctrlKey: true,
        bubbles: true,
      }),
    );
  });
  // The first time it asks; ticking "Don't ask again" stops the question.
  expect(fetcher.mock.calls.some(([path]) => path === "/v1/bug-reports")).toBe(
    false,
  );
  expect(document.body.textContent).toContain("Send this report?");
  const tick = document.querySelector<HTMLInputElement>(
    'dialog input[type="checkbox"]',
  )!;
  await act(async () => tick.click());
  await act(async () => button("Send").click());
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(window.localStorage.getItem("sx-bug-report-keys-send")).toBe(
    "without-asking",
  );
  const sent = fetcher.mock.calls.find(([path]) => path === "/v1/bug-reports");
  expect(sent).toBeTruthy();
  const body = JSON.parse(
    String((sent as unknown as [string, RequestInit])[1].body),
  );
  expect(body.words).toBe("The stage chip did not change after Interested.");
  // An older server does not take the advanced parts yet.
  expect(body.advanced).toBeUndefined();
  expect(onSent).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).toContain(
    "Sent. We'll tell you when it's fixed.",
  );
});

it("writes element comments under the words for the team", () => {
  expect(
    wordsWithComments("It broke", [
      {
        note: "Wrong stage here",
        picked: {
          selector: "li.row > button",
          testid: "lead-row",
          components: ["LeadRow"],
          tag: "button",
          box: { x: 0, y: 0, w: 10, h: 10 },
          moved: false,
        },
      },
    ]),
  ).toBe(
    "It broke\n\nOn the screen:\n1. Wrong stage here\n   LeadRow · testid lead-row · li.row > button",
  );
});
