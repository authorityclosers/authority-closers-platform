import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ReportEvidence } from "../report-contract";
import { COMMON } from "../report-copy";
import { SourceWaveformProvider, type ClipRange } from "../source-waveform";
import { CallTimeline, PlayChip } from "./visuals";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const price: ReportEvidence = {
  segment_id: "price",
  quote: "What is the investment?",
  start_ms: 3_000,
  end_ms: 6_000,
};
const budget: ReportEvidence = {
  ...price,
  segment_id: "budget",
  start_ms: 4_000,
  end_ms: 8_000,
};
const moments = [
  {
    key: "price",
    kind: "Price Moment",
    title: "Price",
    at_ms: 3_000,
    source: price,
  },
  {
    key: "budget",
    kind: "Objection",
    title: "Budget",
    at_ms: 4_000,
    source: budget,
  },
];

let root: Root;
let host: HTMLDivElement;
let player: HTMLAudioElement;
let audioRef: { current: HTMLAudioElement };
let paused: boolean;
let ended: boolean;
let seconds: number;
const select = vi.fn();

beforeEach(() => {
  paused = true;
  ended = false;
  seconds = 0;
  select.mockClear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  player = document.createElement("audio");
  Object.defineProperties(player, {
    paused: { get: () => paused },
    ended: { get: () => ended },
    currentTime: { get: () => seconds },
  });
  audioRef = { current: player };
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

function Harness({ activeRange }: { activeRange: ClipRange | null }) {
  return (
    <SourceWaveformProvider audioRef={audioRef} activeRange={activeRange}>
      <CallTimeline
        durationMs={10_000}
        speech={{ top: [{ start_ms: 0, end_ms: 10_000 }], bottom: [] }}
        moments={moments}
        onSelect={select}
      />
      <PlayChip source={price} title="Price" onSelect={select} />
    </SourceWaveformProvider>
  );
}

function emit(name: string, nextPaused: boolean, nextSeconds: number) {
  paused = nextPaused;
  ended = name === "ended";
  seconds = nextSeconds;
  player.dispatchEvent(new Event(name));
}
const pins = () => [
  ...host.querySelectorAll<HTMLButtonElement>("figure button"),
];

it("keeps timeline pins and play chips in step with the shared player's clip", async () => {
  await act(async () => root.render(<Harness activeRange={price} />));
  const [pricePin, budgetPin] = pins();
  const chip = host.querySelector<HTMLButtonElement>(
    "button[aria-label='Play 00:03: Price']",
  )!;
  await act(async () => emit("play", false, 4.5));
  expect(pricePin.getAttribute("aria-pressed")).toBe("true");
  expect(pricePin.getAttribute("aria-label")).toBe(
    "Pause Price Moment · 00:03: Price",
  );
  expect(pricePin.title).toBe(pricePin.getAttribute("aria-label"));
  expect(chip.getAttribute("aria-pressed")).toBe("true");
  // Another clip overlaps this instant, but did not start the playback.
  expect(budgetPin.getAttribute("aria-pressed")).toBe("false");
  expect(budgetPin.getAttribute("aria-label")).toBe(
    "Play Objection · 00:04: Budget",
  );
  await act(async () => pricePin.click());
  expect(select).toHaveBeenCalledWith(price, "Price");
  await act(async () => emit("pause", true, 4.5));
  expect(pricePin.getAttribute("aria-pressed")).toBe("false");
  expect(pricePin.getAttribute("aria-label")).toBe(
    "Play Price Moment · 00:03: Price",
  );
  expect(chip.getAttribute("aria-pressed")).toBe("false");
  await act(async () => emit("play", false, 4.5));
  await act(async () => emit("timeupdate", false, 6));
  expect(pricePin.getAttribute("aria-pressed")).toBe("false");
  expect(chip.getAttribute("aria-pressed")).toBe("false");
});

it("never marks a timeline clip playing during full-recording playback", async () => {
  await act(async () => root.render(<Harness activeRange={null} />));
  await act(async () => emit("play", false, 4.5));
  expect(pins().map((pin) => pin.getAttribute("aria-pressed"))).toEqual([
    "false",
    "false",
  ]);
});

function LabelledChips({ activeRange }: { activeRange: ClipRange | null }) {
  return (
    <SourceWaveformProvider audioRef={audioRef} activeRange={activeRange}>
      <div data-chip="action">
        <PlayChip
          source={price}
          title="Price"
          label={COMMON.play}
          onSelect={select}
        />
      </div>
      <div data-chip="range">
        <PlayChip
          source={price}
          title="Price range"
          label={COMMON.play}
          range
          onSelect={select}
        />
      </div>
      <div data-chip="compact">
        <PlayChip source={price} title="Price compact" onSelect={select} />
      </div>
      <div data-chip="custom">
        <PlayChip
          source={price}
          title="Price custom"
          label="Hear the price"
          onSelect={select}
        />
      </div>
      <div data-chip="other">
        <PlayChip
          source={budget}
          title="Budget"
          label={COMMON.play}
          onSelect={select}
        />
      </div>
    </SourceWaveformProvider>
  );
}

const labelledChip = (kind: string) =>
  host.querySelector<HTMLButtonElement>(`[data-chip="${kind}"] button`)!;

it.each(["timeupdate", "ended"])(
  "shows the current action and preserves each caption/source through pause and %s",
  async (endEvent) => {
    await act(async () => root.render(<LabelledChips activeRange={price} />));
    const chip = labelledChip("action");
    const range = labelledChip("range");
    const compact = labelledChip("compact");
    const custom = labelledChip("custom");
    const other = labelledChip("other");
    expect(chip.textContent).toBe("00:03 · Play");
    expect(range.textContent).toBe("00:03–00:06 · Play");
    await act(async () => emit("play", false, 4.5));
    expect(chip.textContent).toBe("00:03 · Pause");
    expect(chip.getAttribute("aria-label")).toBe("Pause 00:03: Price");
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    expect(chip.querySelector(".lucide-pause")).not.toBeNull();
    expect(range.textContent).toBe("00:03–00:06 · Pause");
    expect(compact.textContent).toBe("00:03");
    expect(custom.textContent).toBe("00:03 · Hear the price");
    expect(other.textContent).toBe("00:04 · Play");
    expect(other.getAttribute("aria-pressed")).toBe("false");
    for (const [button, title] of [
      [chip, "Price"],
      [range, "Price range"],
      [compact, "Price compact"],
      [custom, "Price custom"],
    ] as const) {
      await act(async () => button.click());
      expect(select.mock.lastCall?.[0]).toBe(price);
      expect(select.mock.lastCall?.[1]).toBe(title);
    }
    await act(async () => emit("pause", true, 4.5));
    expect(chip.textContent).toBe("00:03 · Play");
    expect(range.textContent).toBe("00:03–00:06 · Play");
    expect(chip.getAttribute("aria-label")).toBe("Play 00:03: Price");
    expect(chip.querySelector(".lucide-play")).not.toBeNull();
    await act(async () => emit("play", false, 4.5));
    await act(async () =>
      emit(endEvent, endEvent === "ended", endEvent === "ended" ? 4.5 : 6),
    );
    expect(chip.textContent).toBe("00:03 · Play");
    expect(range.textContent).toBe("00:03–00:06 · Play");
    expect(chip.getAttribute("aria-pressed")).toBe("false");
    expect(compact.textContent).toBe("00:03");
    expect(custom.textContent).toBe("00:03 · Hear the price");
  },
);

it.each([null, budget])(
  "keeps the action Play during full-recording or another overlapping clip playback (%j)",
  async (activeRange) => {
    await act(async () =>
      root.render(<LabelledChips activeRange={activeRange} />),
    );
    await act(async () => emit("play", false, 4.5));
    expect(labelledChip("action").textContent).toBe("00:03 · Play");
    expect(labelledChip("action").getAttribute("aria-pressed")).toBe("false");
    expect(labelledChip("range").textContent).toBe("00:03–00:06 · Play");
    expect(labelledChip("other").textContent).toBe(
      activeRange ? "00:04 · Pause" : "00:04 · Play",
    );
  },
);
