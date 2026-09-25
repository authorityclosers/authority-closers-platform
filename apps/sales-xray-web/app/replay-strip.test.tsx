import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../tests/fixtures/dipak-overview.json";
import type { SalesReport } from "./report-contract";
import {
  countReportMoments,
  reportReplayClips,
  type ReplayClip,
} from "./report-moments";
import { ReplayStrip } from "./replay-strip";

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
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const report = fixture.report as SalesReport;
const clip = (
  start_ms: number,
  end_ms: number,
  title: string,
  segment_id = `s-${start_ms}`,
): ReplayClip => ({
  evidence: { segment_id, quote: `Quote ${title}`, start_ms, end_ms },
  titles: [title],
});

async function render(
  clips: ReplayClip[],
  durationMs: number | undefined,
  onSelect = vi.fn(),
) {
  await act(async () =>
    root.render(
      <ReplayStrip clips={clips} durationMs={durationMs} onSelect={onSelect} />,
    ),
  );
  return onSelect;
}

const markers = () => [
  ...container.querySelectorAll<HTMLButtonElement>("[aria-hidden] button"),
];
const items = () => [
  ...container.querySelectorAll<HTMLButtonElement>("ol button"),
];

it("draws, counts and lists exactly the report's deduplicated replay clips", async () => {
  const clips = reportReplayClips(report);
  expect(clips.length).toBe(countReportMoments(report));
  expect(clips.length).toBeGreaterThan(1);
  // Chronological, one entry per identical interval.
  const starts = clips.map(({ evidence }) => evidence.start_ms);
  expect(starts).toEqual([...starts].sort((a, b) => a - b));
  await render(clips, 60_000);
  expect(markers()).toHaveLength(clips.length);
  expect(items()).toHaveLength(clips.length);
  expect(container.textContent).toContain(
    `${clips.length} of ${clips.length} supplied clips fit fully within the 01:00 recording · positions only, not a score`,
  );
});

it("places each clip only from its own milliseconds and the recording length", async () => {
  await render(
    [clip(15_000, 30_000, "Budget"), clip(45_000, 45_400, "Tiny")],
    60_000,
  );
  const [budget, tiny] = markers();
  expect(budget.style.getPropertyValue("--left")).toBe("25%");
  expect(budget.style.getPropertyValue("--width")).toBe("25%");
  expect(parseFloat(tiny.style.getPropertyValue("--left"))).toBeCloseTo(75);
  // The tiny clip is reachable through a full-size list control.
  expect(items()[1].textContent).toContain("at 00:45 · under 1 second");
});

it("keeps the strip pointer-only and routes keyboard and touch through the list", async () => {
  const onSelect = await render(
    [clip(10_000, 12_000, "Same A", "a"), clip(10_000, 12_500, "Same B", "b")],
    60_000,
  );
  expect(
    container.querySelector(".track, [aria-hidden='true']"),
  ).not.toBeNull();
  expect(markers().every((marker) => marker.tabIndex === -1)).toBe(true);
  const listed = items();
  expect(listed.map((item) => item.getAttribute("aria-label"))).toEqual([
    "Listen 00:10–00:12: Same A",
    "Listen 00:10–00:12: Same B",
  ]);
  await act(async () => listed[1].click());
  expect(onSelect).toHaveBeenCalledWith(
    expect.objectContaining({ segment_id: "b", end_ms: 12_500 }),
    "Same B",
  );
});

it("says so when clips fall outside the recording or timing is unknown", async () => {
  await render(
    [
      clip(5_000, 8_000, "Inside"),
      clip(55_000, 65_000, "Crossing"),
      clip(70_000, 72_000, "After"),
    ],
    60_000,
  );
  expect(markers()).toHaveLength(1);
  // Only the fully in-range clip can be played; crossing/past ranges remain listed.
  expect(items()).toHaveLength(1);
  expect(container.querySelectorAll("ol li")).toHaveLength(3);
  expect(container.textContent).toContain(
    "1 of 3 supplied clips fit fully within the 01:00 recording",
  );
  const beyond = [
    ...container.querySelectorAll<HTMLElement>("[data-replay-beyond]"),
  ];
  expect(beyond).toHaveLength(2);
  expect(beyond[0].textContent).toContain(
    "Crossing · extends past the 01:00 recording",
  );
  expect(beyond[1].textContent).toContain(
    "After · extends past the 01:00 recording",
  );
  expect(container.textContent).toContain(
    "2 clip ranges extend past the 01:00 recording",
  );

  // Unknown length: nothing to check against, so valid clips stay playable.
  await render([clip(5_000, 8_000, "Inside")], undefined);
  expect(markers()).toHaveLength(0);
  expect(container.textContent).toContain("Replay timeline unavailable");
  expect(items()).toHaveLength(1);
});

it("never calls a known length unknown when every clip lies beyond it (R8)", async () => {
  const onSelect = await render(
    [clip(59_000, 61_000, "Crossing"), clip(70_000, 72_000, "After")],
    60_000,
  );
  expect(
    container
      .querySelector("[data-replay-strip]")
      ?.getAttribute("data-replay-strip"),
  ).toBe("beyond");
  expect(container.textContent).not.toContain("length is not known");
  expect(container.textContent).not.toContain("length unavailable");
  expect(container.textContent).toContain(
    "0 of 2 supplied clips fit fully within the 01:00 recording",
  );
  expect(container.textContent).toContain(
    "None of the 2 clip ranges fit fully within the 01:00 recording, so they are not drawn or playable.",
  );
  expect(
    container.querySelector("[data-replay-beyond]")?.textContent,
  ).toContain("Crossing · extends past the 01:00 recording");
  // No marker, no playback control, no seek can be issued.
  expect(markers()).toHaveLength(0);
  expect(items()).toHaveLength(0);
  expect(container.querySelectorAll("[data-replay-beyond]")).toHaveLength(2);
  container
    .querySelectorAll<HTMLElement>("[data-replay-beyond]")
    .forEach((entry) => entry.click());
  expect(onSelect).not.toHaveBeenCalled();
});

it("never lists or plays an excerpt without a forward time range", async () => {
  await render(
    [clip(5_000, 5_000, "Empty"), clip(9_000, 8_000, "Reversed")],
    60_000,
  );
  expect(items()).toHaveLength(0);
  expect(markers()).toHaveLength(0);
  expect(container.textContent).toContain(
    "2 excerpts have no playable time range and are not listed.",
  );
});

it("renders nothing when the report supplied no replay clips", async () => {
  await render([], 60_000);
  expect(container.querySelector("[data-replay-strip]")).toBeNull();
});
