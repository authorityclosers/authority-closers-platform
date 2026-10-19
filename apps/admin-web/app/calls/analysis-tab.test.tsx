// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AnalysisTab } from "./analysis-tab";
import { normalizeCallDetail } from "./call-detail-data";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const DETAIL = normalizeCallDetail({
  call: {
    recording_id: "r-1",
    organisation: { name: "Fictional Org", kind: "customer" },
  },
  runs: [
    { run_id: "r2", pipeline: "deep", state: "failed" },
    { run_id: "r1", pipeline: "fast", state: "succeeded" },
  ],
  objects: [{ object_id: "f-1", type: "need", current: true }],
  totals: { call: { cost_inr: 2.4, tokens_in: 6190, tokens_out: 900 } },
  categories: { needs: "Needs and goals" },
  facts: [
    {
      object_id: "f-1",
      type: "need",
      category: "needs",
      label: "Main need",
      display: "More site visits confirmed in writing",
      confidence: 0.92,
      basis: "confirmed",
      source: { pipeline: "deep" },
      evidence: [
        {
          start_ms: 95_000,
          end_ms: 99_000,
          quote: "Confirm visits in writing",
          role: "prospect",
        },
        {
          start_ms: 42_000,
          end_ms: 45_000,
          quote: "Visits go unrecorded",
          role: "prospect",
        },
      ],
    },
    {
      object_id: "f-2",
      type: "objection",
      category: "needs",
      label: "Worry",
      display: "Paying before the scope fits",
      confidence: 0.81,
      basis: "inferred",
      source: { pipeline: "fast" },
    },
  ],
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

it("lists facts under their category, whose word each is, and jumps to each moment", async () => {
  const onSeek = vi.fn();
  await act(async () =>
    root.render(
      <AnalysisTab detail={DETAIL} recordingId="r-1" onSeek={onSeek} />,
    ),
  );
  expect(host.textContent).toContain("Needs and goals 2");
  expect(host.textContent).toContain("Person · confirmed");
  expect(host.textContent).toContain("AI · inferred");
  expect(host.textContent).toContain("Fast succeeded");
  expect(host.textContent).toContain("Deep failed");
  expect(host.textContent).toContain("6.2k in");
  const moments = [...host.querySelectorAll("button")];
  // Earliest moment first.
  expect(moments.map((button) => button.textContent)).toEqual([
    "▶ 0:42",
    "▶ 1:35",
  ]);
  await act(async () => moments[0].click());
  expect(onSeek).toHaveBeenCalledWith(42_000);
  expect(host.querySelector('a[href="/calls/r-1/map"]')).not.toBeNull();
});

it("says so when the engine has not read the call", async () => {
  await act(async () =>
    root.render(
      <AnalysisTab detail={null} recordingId="r-1" onSeek={() => {}} />,
    ),
  );
  expect(host.textContent).toContain("hasn’t read this call yet");
  expect(host.querySelector('a[href="/calls/r-1/map"]')).not.toBeNull();
});
