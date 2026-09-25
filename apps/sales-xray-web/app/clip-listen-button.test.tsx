import { act, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ClipListenButton,
  SourceWaveformProvider,
  clipIsPlaying,
  clipPressAction,
  type ClipRange,
} from "./source-waveform";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
let player: HTMLAudioElement | null = null;
let paused = true;
let seconds = 0;
beforeEach(() => {
  paused = true;
  seconds = 0;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

const price: ClipRange = { start_ms: 3_000, end_ms: 6_000 };
const overlap: ClipRange = { start_ms: 4_000, end_ms: 8_000 };

function controlledAudio(element: HTMLAudioElement | null) {
  player = element;
  if (!element) return;
  Object.defineProperty(element, "paused", {
    configurable: true,
    get: () => paused,
  });
  Object.defineProperty(element, "currentTime", {
    configurable: true,
    get: () => seconds,
  });
}

function Harness({
  activeRange,
  submissionId = "call-a",
}: {
  activeRange: ClipRange | null;
  submissionId?: string;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  return (
    <SourceWaveformProvider
      audioRef={audio}
      activeRange={activeRange}
      submissionId={submissionId}
    >
      <audio
        ref={(element) => {
          audio.current = element;
          controlledAudio(element);
        }}
      />
      <ClipListenButton
        startMs={price.start_ms}
        endMs={price.end_ms}
        label="00:03–00:06: Price question"
        onClick={() => {}}
      />
      <ClipListenButton
        startMs={overlap.start_ms}
        endMs={overlap.end_ms}
        label="00:04–00:08: Budget"
        onClick={() => {}}
      />
    </SourceWaveformProvider>
  );
}

function emit(name: string, nextPaused: boolean, nextSeconds: number) {
  paused = nextPaused;
  seconds = nextSeconds;
  player!.dispatchEvent(new Event(name));
}

const buttons = () => [...container.querySelectorAll("button")];

vi.stubGlobal(
  "fetch",
  vi.fn(() => new Promise(() => {})),
);

it("shows Pause only on the clip that started the one shared playback", async () => {
  await act(async () => root.render(<Harness activeRange={price} />));
  const [first, second] = buttons();
  expect(first.textContent).toBe("Listen");
  expect(first.getAttribute("aria-pressed")).toBe("false");

  await act(async () => emit("play", false, 4.5));
  expect(first.textContent).toBe("Pause");
  expect(first.getAttribute("aria-label")).toBe(
    "Pause 00:03–00:06: Price question",
  );
  // The overlapping clip is inside the playhead too, but did not start it.
  expect(second.textContent).toBe("Listen");

  await act(async () => emit("pause", true, 4.5));
  expect(first.textContent).toBe("Listen");
});

it("reads an element that is already playing when the provider subscribes", async () => {
  paused = false;
  seconds = 3.5;
  await act(async () => root.render(<Harness activeRange={price} />));
  expect(buttons()[0].textContent).toBe("Pause");
});

it("clears a stale playing state when the source resets without a pause event", async () => {
  await act(async () => root.render(<Harness activeRange={price} />));
  await act(async () => emit("play", false, 4));
  expect(buttons()[0].textContent).toBe("Pause");
  // A new src runs the media load algorithm: paused flips, "emptied" fires.
  await act(async () => emit("emptied", true, 0));
  expect(buttons()[0].textContent).toBe("Listen");
});

it("re-reads the element when the bound call changes", async () => {
  await act(async () => root.render(<Harness activeRange={price} />));
  await act(async () => emit("play", false, 4));
  paused = true;
  seconds = 0;
  await act(async () =>
    root.render(<Harness activeRange={price} submissionId="call-b" />),
  );
  expect(buttons()[0].textContent).toBe("Listen");
});

describe("clip press decisions", () => {
  const base = { paused: false, currentTimeMs: 4_000, activeRange: price };
  it("pauses the active clip, resumes in place and restarts after its end", () => {
    expect(clipPressAction(price, base)).toBe("pause");
    expect(clipPressAction(price, { ...base, paused: true })).toBe("resume");
    expect(
      clipPressAction(price, { ...base, paused: true, currentTimeMs: 6_000 }),
    ).toBe("start");
    expect(
      clipPressAction(price, { ...base, paused: true, currentTimeMs: 3_000 }),
    ).toBe("start");
  });
  it("starts a different or overlapping clip instead of pausing it", () => {
    expect(clipPressAction(overlap, base)).toBe("start");
    expect(clipPressAction(price, { ...base, activeRange: null })).toBe(
      "start",
    );
  });
  it("never claims a clip during full-recording playback", () => {
    expect(
      clipIsPlaying(price, {
        playing: true,
        currentTimeMs: 4_000,
        activeRange: null,
      }),
    ).toBe(false);
  });
});
