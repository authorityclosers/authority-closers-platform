// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PracticeSoundControls } from "./practice-sound-controls";
import {
  PRACTICE_VOLUME_KEY,
  readPracticeVolume,
  savePracticeSounds,
  savePracticeVolume,
} from "../lib/practice-sounds";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
const makePlayer = () => ({
  prepare: vi.fn(async () => {}),
  play: vi.fn(() => true),
  preview: vi.fn(async () => true),
  setEnabled: vi.fn(),
  setVolume: vi.fn(),
  stop: vi.fn(),
  dispose: vi.fn(),
});
let player: ReturnType<typeof makePlayer>;
beforeEach(async () => {
  window.localStorage.clear();
  player = makePlayer();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () =>
    root.render(<PracticeSoundControls getPlayer={() => player} />),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});
const control = (label: string) =>
  container.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)!;
const click = async (element: HTMLElement) => {
  await act(async () => element.click());
};

it("opens a compact settings dialog without autoplay, closes with Escape and restores focus", async () => {
  const trigger = control("Practice sound settings");
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  await click(trigger);
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  expect(document.activeElement).toBe(control("Practice sound effects"));
  expect(player.prepare).not.toHaveBeenCalled();
  expect(player.play).not.toHaveBeenCalled();
  await act(async () =>
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    ),
  );
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

it("keeps previews off until explicitly enabled, then plays only an explicitly requested sample", async () => {
  await click(control("Practice sound settings"));
  const celebrate = () =>
    [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (el) => el.textContent === "Celebrate",
    )!;
  expect(celebrate().disabled).toBe(true);
  await click(control("Practice sound effects"));
  expect(player.setEnabled).toHaveBeenLastCalledWith(true);
  expect(player.prepare).toHaveBeenCalledOnce();
  expect(player.preview).not.toHaveBeenCalled();
  await click(celebrate());
  expect(player.preview).toHaveBeenCalledExactlyOnceWith("reward");
  expect(container.textContent).toContain("No practice progress changes");
  expect(player.play).not.toHaveBeenCalled();
  await click(control("Practice sound effects"));
  expect(player.setEnabled).toHaveBeenLastCalledWith(false);
});

it("refreshes saved volume across settings and does not offer an inaudible preview", async () => {
  await act(async () => {
    savePracticeSounds(true);
    savePracticeVolume(0);
  });
  await click(control("Practice sound settings"));
  expect(container.querySelector("output")?.textContent).toBe("0%");
  expect(
    [...container.querySelectorAll("button")].find(
      (el) => el.textContent === "Celebrate",
    )?.disabled,
  ).toBe(true);
  await act(async () => savePracticeVolume(0.8));
  expect(container.querySelector("output")?.textContent).toBe("80%");
  expect(window.localStorage.getItem(PRACTICE_VOLUME_KEY)).toBe("0.8");
});

it("bounds malformed persisted volume and stays quiet when a preview resolves after close", async () => {
  window.localStorage.setItem(PRACTICE_VOLUME_KEY, "not-a-volume");
  expect(readPracticeVolume()).toBe(0.65);
  await act(async () => savePracticeSounds(true));
  let finish!: (value: boolean) => void;
  player.preview.mockImplementation(
    () =>
      new Promise<boolean>((resolve) => {
        finish = resolve;
      }),
  );
  await click(control("Practice sound settings"));
  await click(
    [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (el) => el.textContent === "Celebrate",
    )!,
  );
  await click(control("Close sound settings"));
  await act(async () => finish(true));
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(player.stop).toHaveBeenCalled();
});
