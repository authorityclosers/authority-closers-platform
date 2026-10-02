import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { CallSignals, clearPromisesDone } from "./call-signals";
import type { Transcript } from "./report-contract";
import { ReportReadingProvider } from "./report-reading-context";
import { saveSpeakerProfiles } from "./speaker-profiles";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const CALL = "3c9e1f40-7b2d-4e8a-9f61-0d5a2b7c4e18";
const PROMISES = `ac.xray.promises-done.v1:${CALL}`;

// Fictional: the buyer only reads serial numbers, and the rep only asks
// about a budget. Neither is openness, and no price is ever stated.
const transcript: Transcript = {
  source_sha256: "0".repeat(64),
  revision: "signals-r1",
  timebase_id: "1ms",
  duration_ms: 180_000,
  segments: [
    ["rep", 0, 6_000, "Hello, this is a short call about your order."],
    ["buyer", 6_500, 50_000, "Serial one is A1 B2 C3, serial two is D4 E5."],
    ["rep", 60_000, 64_000, "What is your budget?"],
    ["buyer", 69_000, 72_000, "We have not set one yet."],
  ].map(([speaker, start, end, text], index) => ({
    id: `s${index + 1}`,
    speaker_id: speaker as string,
    start_ms: start as number,
    end_ms: end as number,
    text: text as string,
  })),
};

let root: Root;
let host: HTMLDivElement;

beforeEach(async () => {
  localStorage.clear();
  saveSpeakerProfiles(CALL, {
    rep: { name: "Fictional Rep", role: "salesperson", icon: null },
    buyer: { name: "Fictional Buyer", role: "prospect", icon: null },
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <CallSignals callId={CALL} transcript={transcript} onSeek={vi.fn()} />,
    ),
  );
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  localStorage.clear();
});

it("labels the prospect's peak as talk share, never as opening up", () => {
  expect(host.textContent).toContain("Their highest talk share at");
  expect(host.textContent?.toLowerCase()).not.toContain("opened up");
});

it("calls a budget question a price or budget mention, not a stated price", () => {
  expect(host.textContent).toContain("After a price or budget mention");
  expect(host.textContent).not.toContain("said the price");
});

it("clears ticked promises for one call only", () => {
  const other = "ac.xray.promises-done.v1:another-call";
  localStorage.setItem(PROMISES, '["s1:I will send the fictional brochure."]');
  localStorage.setItem(other, "[]");
  expect(clearPromisesDone(CALL)).toBe(true);
  expect(localStorage.getItem(PROMISES)).toBeNull();
  expect(localStorage.getItem(other)).toBe("[]");
});

it("includes talk-overs beyond the six-row preview in Document", async () => {
  const source: Transcript = {
    ...transcript,
    segments: Array.from({ length: 8 }, (_, index) => [
      {
        id: `buyer-${index}`,
        speaker_id: "buyer",
        start_ms: index * 10_000,
        end_ms: index * 10_000 + 8_000,
        text: `Fictional buyer detail ${index + 1}.`,
      },
      {
        id: `rep-${index}`,
        speaker_id: "rep",
        start_ms: index * 10_000 + 1_000,
        end_ms: index * 10_000 + 2_000,
        text: `Fictional interruption ${index + 1}.`,
      },
    ]).flat(),
  };
  const render = async (documentView: boolean) =>
    act(async () =>
      root.render(
        <ReportReadingProvider
          reading={documentView}
          documentView={documentView}
        >
          <CallSignals callId={CALL} transcript={source} onSeek={vi.fn()} />
        </ReportReadingProvider>,
      ),
    );
  const card = () =>
    [...host.querySelectorAll("section")].find((element) =>
      element.querySelector("h3")?.textContent?.includes("Talked over them"),
    )!;
  await render(false);
  expect(card().querySelectorAll("li")).toHaveLength(6);
  await render(true);
  expect(card().querySelectorAll("li")).toHaveLength(8);
  expect(card().textContent).toContain("Fictional interruption 8.");
  expect(card().textContent).toContain("Fictional buyer detail 8.");
});
