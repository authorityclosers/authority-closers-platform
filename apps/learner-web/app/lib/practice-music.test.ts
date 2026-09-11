// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  PRACTICE_MUSIC_ASSET,
  PRACTICE_MUSIC_KEY,
  PRACTICE_MUSIC_VOLUME,
  createPracticeMusicPlayer,
  readPracticeMusic,
  savePracticeMusic,
  subscribePracticeMusic,
} from "./practice-music";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
beforeEach(() => window.localStorage.clear());

function fixture() {
  let visible = true;
  let finishPlay!: () => void;
  const audio = {
    src: "",
    preload: "auto",
    loop: false,
    volume: 1,
    currentTime: 7,
    play: vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishPlay = resolve;
        }),
    ),
    pause: vi.fn(),
    removeAttribute: vi.fn(),
  };
  const createAudio = vi.fn(() => audio as unknown as HTMLAudioElement);
  const changes: boolean[] = [];
  const player = createPracticeMusicPlayer({
    createAudio,
    visible: () => visible,
    onPlayingChange: (playing) => changes.push(playing),
  });
  return {
    audio,
    changes,
    createAudio,
    finishPlay: () => finishPlay(),
    hide: () => {
      visible = false;
      document.dispatchEvent(new Event("visibilitychange"));
    },
    player,
  };
}

it("stores a separate off-by-default presentation preference", () => {
  const changed = vi.fn();
  const unsubscribe = subscribePracticeMusic(changed);
  expect(readPracticeMusic()).toBe(false);
  savePracticeMusic(true);
  expect(readPracticeMusic()).toBe(true);
  expect(window.localStorage.getItem(PRACTICE_MUSIC_KEY)).toBe("on");
  expect(changed).toHaveBeenCalledOnce();
  savePracticeMusic(false);
  expect(readPracticeMusic()).toBe(false);
  unsubscribe();
});

it("does not construct, load or play audio before an explicit start", async () => {
  const f = fixture();
  expect(f.createAudio).not.toHaveBeenCalled();
  const started = f.player.start();
  expect(f.createAudio).toHaveBeenCalledOnce();
  expect(f.audio).toMatchObject({
    src: PRACTICE_MUSIC_ASSET,
    preload: "none",
    loop: true,
    volume: PRACTICE_MUSIC_VOLUME,
  });
  expect(f.audio.play).toHaveBeenCalledOnce();
  f.finishPlay();
  await expect(started).resolves.toBe(true);
  expect(f.player.isPlaying()).toBe(true);
  expect(f.changes).toEqual([true]);
  f.player.dispose();
});

it("coalesces repeated starts and a stop prevents late playback state", async () => {
  const f = fixture();
  const first = f.player.start();
  const second = f.player.start();
  expect(second).toBe(first);
  expect(f.audio.play).toHaveBeenCalledOnce();
  f.player.stop();
  expect(f.audio.pause).toHaveBeenCalledOnce();
  expect(f.audio.currentTime).toBe(0);
  f.finishPlay();
  await expect(first).resolves.toBe(false);
  expect(f.player.isPlaying()).toBe(false);
  f.player.dispose();
});

it("stops when hidden or page-exited and never resumes itself", async () => {
  const f = fixture();
  const started = f.player.start();
  f.finishPlay();
  await started;
  f.hide();
  expect(f.audio.pause).toHaveBeenCalledOnce();
  expect(f.player.isPlaying()).toBe(false);
  document.dispatchEvent(new Event("pagehide"));
  expect(f.audio.pause).toHaveBeenCalledTimes(2);
  expect(f.audio.play).toHaveBeenCalledOnce();
  f.player.dispose();
});

it("bounds a stalled start and disposal removes the fixed source", async () => {
  vi.useFakeTimers();
  const f = fixture();
  const started = f.player.start();
  await vi.advanceTimersByTimeAsync(4000);
  await expect(started).resolves.toBe(false);
  expect(f.audio.pause).toHaveBeenCalledOnce();
  expect(f.player.isPlaying()).toBe(false);
  f.player.dispose();
  expect(f.audio.removeAttribute).toHaveBeenCalledWith("src");
  await expect(f.player.start()).resolves.toBe(false);
});

it("treats unsupported audio as an optional no-op", async () => {
  const player = createPracticeMusicPlayer({
    createAudio: () => {
      throw new Error("audio unavailable");
    },
  });
  await expect(player.start()).resolves.toBe(false);
  expect(player.isPlaying()).toBe(false);
  player.dispose();
});
