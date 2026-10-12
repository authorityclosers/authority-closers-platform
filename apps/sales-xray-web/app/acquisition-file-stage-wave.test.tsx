import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { WaveformEnvelope } from "./source-waveform";

// The browser's measurement of the chosen file (decoded locally).
const measured = vi.hoisted(() => ({ envelope: null as unknown }));
vi.mock("./analysis-wave-file", () => ({
  useFileWave: (file: File | null) => (file ? measured.envelope : null),
}));

const { AcquisitionFileStage } = await import("./acquisition-file-stage");

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const call = new File([new Uint8Array(2048)], "Discovery call.m4a", {
  type: "audio/mp4",
});
const wave = (durationMs: number): WaveformEnvelope => ({
  schema: "ac.sales-xray.waveform/1",
  kind: "rms_envelope",
  duration_ms: durationMs,
  points: Array.from({ length: 60 }, (_, index) => ({
    start_ms: Math.floor((index * durationMs) / 60),
    level: index % 3 ? 0.05 : 0.2,
  })),
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const render = () =>
  act(async () =>
    root.render(
      <AcquisitionFileStage
        files={[call]}
        selectedFile={call}
        maxBytes={32 * 1048576}
        maxMinutes={60}
        disabled={false}
        onSelect={() => {}}
        onRemove={() => {}}
        onClear={() => {}}
        onAddFiles={() => {}}
      />,
    ),
  );

it("draws the chosen call's own wave and says how long it is", async () => {
  measured.envelope = wave(1_508_000);
  await render();
  const card = host.querySelector('li[data-selected="true"]')!;
  expect(card.textContent).toContain("2 KB · 25:08 · Recording");
  const strip = card.querySelector('[role="img"]')!;
  expect(strip.hasAttribute("data-measured")).toBe(true);
  expect(strip.getAttribute("aria-label")).toBe(
    "Your call's sound level over its length",
  );
  // A quiet recording still fills the strip: its loud end reaches the top.
  const heights = [...strip.querySelectorAll("i")].map((bar) =>
    parseInt((bar as HTMLElement).style.getPropertyValue("--h"), 10),
  );
  expect(Math.max(...heights)).toBe(100);
});

it("says before sending when a call is longer than the plan allows", async () => {
  measured.envelope = wave(72 * 60_000);
  await render();
  expect(host.textContent).toContain("1:12:00 · Longer than 60 min");
});
