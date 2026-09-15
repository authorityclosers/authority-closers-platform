import { act, createRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CallAudioDock } from "./call-audio-dock";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

it("uses one real audio element for playback, speed, mute and evidence pause callbacks", async () => {
  const audio = createRef<HTMLAudioElement>();
  const update = vi.fn();
  await act(async () =>
    root.render(
      <CallAudioDock
        audioRef={audio}
        src="/authorized/source"
        durationMs={1253000}
        onTimeUpdate={update}
      />,
    ),
  );
  expect(container.querySelectorAll("audio")).toHaveLength(1);
  expect(audio.current?.getAttribute("src")).toBe("/authorized/source");
  const play = vi.spyOn(audio.current!, "play").mockImplementation(async () => {
    audio.current?.dispatchEvent(new Event("play"));
  });
  await act(async () =>
    (
      container.querySelector(
        '[aria-label="Play recording"]',
      ) as HTMLButtonElement
    ).click(),
  );
  expect(play).toHaveBeenCalledOnce();
  expect(
    container.querySelector('[aria-label="Pause recording"]'),
  ).not.toBeNull();
  await act(async () =>
    (
      container.querySelector(
        '[aria-label="Playback speed 1 times"]',
      ) as HTMLButtonElement
    ).click(),
  );
  expect(audio.current?.playbackRate).toBe(1.25);
  await act(async () =>
    (
      container.querySelector(
        '[aria-label="Mute recording"]',
      ) as HTMLButtonElement
    ).click(),
  );
  expect(audio.current?.muted).toBe(true);
  await act(async () => {
    audio.current!.currentTime = 14;
    audio.current?.dispatchEvent(new Event("timeupdate"));
  });
  expect(update).toHaveBeenCalled();
  expect(
    container
      .querySelector('[aria-label="Seek recording"]')
      ?.getAttribute("aria-valuetext"),
  ).toBe("00:14 of 20:53");
});

it("keeps report-safe playback failures readable without fabricating waveform data", async () => {
  const audio = createRef<HTMLAudioElement>();
  await act(async () =>
    root.render(
      <CallAudioDock
        audioRef={audio}
        src="/authorized/source"
        durationMs={60000}
      />,
    ),
  );
  vi.spyOn(audio.current!, "play").mockRejectedValue(
    new Error("private internals"),
  );
  await act(async () =>
    (
      container.querySelector(
        '[aria-label="Play recording"]',
      ) as HTMLButtonElement
    ).click(),
  );
  expect(container.textContent).toContain(
    "Audio could not start. Try play again.",
  );
  expect(container.textContent).not.toContain("private internals");
  expect(
    container.querySelector('[aria-label="Audio level preview unavailable"]'),
  ).not.toBeNull();
  expect(
    container.querySelector('[aria-label="Recorded audio level"]'),
  ).toBeNull();
});
