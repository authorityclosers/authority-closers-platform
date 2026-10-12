import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ReportEvidence } from "../report-contract";
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
let seconds: number;
const select = vi.fn();

beforeEach(() => {
  paused = true;
  seconds = 0;
  select.mockClear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  player = document.createElement("audio");
  Object.defineProperties(player, {
    paused: { get: () => paused },
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
