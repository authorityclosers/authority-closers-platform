import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import fixture from "../tests/fixtures/dipak-overview.json";
import { readCallFacts } from "./call-facts";
import { KeyFacts } from "./key-facts";
import type { SalesReport, Transcript } from "./report-contract";
import { saveSpeakerProfiles } from "./speaker-profiles";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const CALL = "5b7a0d2e-8c4f-4a61-9d3e-2f1b0c9a8e77";
const report = {
  ...(fixture.report as SalesReport),
  summary: "A carpentry business owner in Ahmedabad asked about growth.",
};
const transcript: Transcript = {
  ...(fixture.transcript as Transcript),
  duration_ms: 1_440_000,
  segments: [
    {
      id: "a1",
      speaker_id: "rep",
      start_ms: 0,
      end_ms: 9_000,
      text: "नमस्ते, मुझे 10 15 minute का time लगेगा।",
    },
    {
      id: "a2",
      speaker_id: "buyer",
      start_ms: 9_500,
      end_ms: 14_000,
      text: "10 minute तक चलेगा।",
    },
    {
      id: "a3",
      speaker_id: "buyer",
      start_ms: 240_000,
      end_ms: 250_000,
      text: "हां 1 CR होता है yearly.",
    },
    {
      id: "a4",
      speaker_id: "rep",
      start_ms: 1_300_000,
      end_ms: 1_320_000,
      text: "इसका price अलग अलग category का है।",
    },
  ],
};

let root: Root;
let host: HTMLDivElement;
let onSeek: ReturnType<typeof vi.fn<(ms: number) => void>>;

beforeEach(async () => {
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  onSeek = vi.fn();
  await render();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
});

async function render() {
  await act(async () =>
    root.render(
      <KeyFacts
        callId={CALL}
        transcript={transcript}
        report={report}
        durationMs={transcript.duration_ms}
        onSeek={onSeek}
      />,
    ),
  );
}

function row(label: string) {
  return Array.from(host.querySelectorAll("div")).find(
    (element) => element.firstElementChild?.textContent === label,
  )!;
}

it("shows only what the call really said, with a play button for each", async () => {
  expect(row("Time asked for").textContent).toContain("Up to 15 min");
  expect(row("Time asked for").textContent).toContain("call took 24 min");
  expect(row("Price or budget").textContent).toContain("no amount said");
  expect(row("Industry").textContent).toContain("Carpentry");
  const play = row("Time asked for").querySelector("button")!;
  await act(async () => play.click());
  expect(onSeek).toHaveBeenCalledWith(0);
});

it("confirms a guessed fact in one tap", async () => {
  const yes = Array.from(row("Industry").querySelectorAll("button")).find(
    (button) => button.textContent === "Yes",
  )!;
  await act(async () => yes.click());
  expect(readCallFacts(CALL).confirmed.industry).toBe(true);
  expect(row("Industry").textContent).toContain("Confirmed");
});

it("lets the person say what a heard number means", async () => {
  const select = host.querySelector<HTMLSelectElement>(
    'select[aria-label="What is 1 CR?"]',
  )!;
  await act(async () => {
    select.value = "Yearly sales";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(readCallFacts(CALL).numberLabels["a3:0"]).toBe("Yearly sales");
});

it("names the people once the call map has them", async () => {
  expect(row("Who is on the call").textContent).toContain("Not named yet");
  await act(async () => {
    saveSpeakerProfiles(CALL, {
      rep: { name: "Manas", role: "salesperson", icon: null },
      buyer: { name: "Nandlal ji", role: "prospect", icon: null },
    });
  });
  expect(row("Who is on the call").textContent).toContain(
    "Manas (salesperson) · Nandlal ji (prospect)",
  );
});
