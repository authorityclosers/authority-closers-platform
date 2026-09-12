// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PRACTICE_MUSIC_KEY, savePracticeMusic } from "../lib/practice-music";
import {
  DEFAULT_PRACTICE_VOLUME,
  PRACTICE_VOLUME_KEY,
  savePracticeSounds,
  savePracticeVolume,
} from "../lib/practice-sounds";
import { PracticeSoundControls } from "./practice-sound-controls";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
const makeSoundPlayer = () => ({
  prepare: vi.fn(async () => {}),
  play: vi.fn(() => true),
  preview: vi.fn(async () => true),
  setEnabled: vi.fn(),
  setVolume: vi.fn(),
  stop: vi.fn(),
  dispose: vi.fn(),
});
const makeMusicPlayer = () => ({
  start: vi.fn(async () => true),
  stop: vi.fn(),
  isPlaying: vi.fn(() => false),
  dispose: vi.fn(),
});
let soundPlayer: ReturnType<typeof makeSoundPlayer>;
let musicPlayer: ReturnType<typeof makeMusicPlayer>;
let musicChanged: (playing: boolean) => void;

beforeEach(async () => {
  window.localStorage.clear();
  soundPlayer = makeSoundPlayer();
  musicPlayer = makeMusicPlayer();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <PracticeSoundControls
        getPlayer={() => soundPlayer}
        createMusicPlayer={(changed) => {
          musicChanged = changed;
          return musicPlayer;
        }}
      />,
    ),
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

it("renders direct effects and music toggles without a menu or autoplay", () => {
  expect(control("Unmute practice sounds")).not.toBeNull();
  expect(control("Play background music")).not.toBeNull();
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(soundPlayer.prepare).not.toHaveBeenCalled();
  expect(soundPlayer.play).not.toHaveBeenCalled();
  expect(musicPlayer.start).not.toHaveBeenCalled();
});

it("mutes and unmutes sound effects with one tap", async () => {
  await click(control("Unmute practice sounds"));
  expect(soundPlayer.setEnabled).toHaveBeenLastCalledWith(true);
  expect(soundPlayer.prepare).toHaveBeenCalledOnce();
  expect(control("Mute practice sounds").getAttribute("aria-pressed")).toBe(
    "true",
  );
  await click(control("Mute practice sounds"));
  expect(soundPlayer.setEnabled).toHaveBeenLastCalledWith(false);
  expect(control("Unmute practice sounds").getAttribute("aria-pressed")).toBe(
    "false",
  );
});

it("restores a safe audible level when unmuting a previously zero-volume choice", async () => {
  await act(async () => {
    savePracticeSounds(true);
    savePracticeVolume(0);
  });
  await click(control("Unmute practice sounds"));
  expect(soundPlayer.setVolume).toHaveBeenCalledWith(DEFAULT_PRACTICE_VOLUME);
  expect(soundPlayer.setEnabled).toHaveBeenCalledWith(true);
  expect(window.localStorage.getItem(PRACTICE_VOLUME_KEY)).toBe(
    String(DEFAULT_PRACTICE_VOLUME),
  );
});

it("starts music only from its tap and stops it with the same direct control", async () => {
  musicPlayer.start.mockImplementation(async () => {
    musicChanged(true);
    return true;
  });
  await click(control("Play background music"));
  expect(musicPlayer.start).toHaveBeenCalledOnce();
  expect(window.localStorage.getItem(PRACTICE_MUSIC_KEY)).toBe("on");
  expect(control("Stop background music").getAttribute("aria-pressed")).toBe(
    "true",
  );
  await click(control("Stop background music"));
  expect(musicPlayer.stop).toHaveBeenCalled();
  expect(window.localStorage.getItem(PRACTICE_MUSIC_KEY)).toBe("off");
});

it("cancels an in-flight start when the saved music preference turns off", async () => {
  let finishStart: (started: boolean) => void = () => {};
  musicPlayer.start.mockImplementation(
    () =>
      new Promise<boolean>((resolve) => {
        finishStart = resolve;
      }),
  );
  await click(control("Play background music"));
  expect(control("Stop background music").dataset.starting).toBe("true");

  await act(async () => savePracticeMusic(false));
  expect(musicPlayer.stop).toHaveBeenCalled();
  expect(control("Play background music").dataset.starting).toBe("false");

  await act(async () => finishStart(true));
  expect(window.localStorage.getItem(PRACTICE_MUSIC_KEY)).toBe("off");
  expect(control("Play background music")).not.toBeNull();
});

it("fails optional music closed and disposes it on exit", async () => {
  musicPlayer.start.mockResolvedValue(false);
  await click(control("Play background music"));
  expect(window.localStorage.getItem(PRACTICE_MUSIC_KEY)).toBe("off");
  expect(control("Play background music")).not.toBeNull();
  expect(container.textContent).toContain(
    "Background music is unavailable right now.",
  );
  await act(async () => root.unmount());
  expect(musicPlayer.dispose).toHaveBeenCalledOnce();
  root = createRoot(container);
});
