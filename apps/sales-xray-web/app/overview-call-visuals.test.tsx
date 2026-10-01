// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../tests/fixtures/call-map-v1.json";
import { parseCallMap } from "./call-map-contract";
import { OverviewCallVisuals } from "./overview-call-visuals";
import type { Transcript } from "./report-contract";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const transcript: Transcript = {
  source_sha256: "0".repeat(64),
  revision: "fictional-visuals-test",
  timebase_id: "1ms",
  duration_ms: 60_000,
  segments: [
    {
      id: "a",
      speaker_id: "alex",
      start_ms: 1_000,
      end_ms: 21_000,
      text: "Why? When?",
    },
    {
      id: "b",
      speaker_id: "sam",
      start_ms: 22_000,
      end_ms: 32_000,
      text: "Thanks.",
    },
    {
      id: "c",
      speaker_id: "lee",
      start_ms: 33_000,
      end_ms: 43_000,
      text: "Agreed.",
    },
  ],
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("measures every speaker without roles, omits AI cards and seeks the longest monologue", async () => {
  const seek = vi.fn();
  await act(async () =>
    root.render(<OverviewCallVisuals transcript={transcript} onSeek={seek} />),
  );
  expect(
    [...host.querySelectorAll("h4")].slice(0, 3).map((h) => h.textContent),
  ).toEqual(["alex", "sam", "lee"]);
  const alex = host.querySelector("h4")!.parentElement!;
  expect(alex.textContent).toContain("Talk time: 00:20");
  expect(alex.textContent).toContain("50% talk share");
  expect(alex.textContent).toContain("Questions: 2");
  expect(host.textContent).toContain("Time used01:00");
  expect(
    host.querySelector('[aria-label="Call map AI visual readings"]'),
  ).toBeNull();
  expect(host.textContent).not.toMatch(
    /assign roles|Verdict|score|grade|percent.good/i,
  );
  const longest = [...host.querySelectorAll("button")].find((b) =>
    b.getAttribute("aria-label")?.endsWith("at 00:01"),
  )!;
  await act(async () => longest.click());
  expect(seek).toHaveBeenCalledExactlyOnceWith(1_000);
});

it("marks a measured quiet start and labels its later recovery", async () => {
  const quietCall: Transcript = {
    ...transcript,
    duration_ms: 300_000,
    segments: [
      {
        id: "q",
        speaker_id: "sam",
        start_ms: 0,
        end_ms: 60_000,
        text: "Hello.",
      },
      {
        id: "long",
        speaker_id: "alex",
        start_ms: 60_000,
        end_ms: 240_000,
        text: "Fictional explanation.",
      },
      {
        id: "recovery",
        speaker_id: "sam",
        start_ms: 240_000,
        end_ms: 300_000,
        text: "I have a question?",
      },
    ],
  };
  await act(async () =>
    root.render(
      <OverviewCallVisuals transcript={quietCall} onSeek={() => undefined} />,
    ),
  );
  const sam = [...host.querySelectorAll("h4")].find(
    (h) => h.textContent === "sam",
  )!.parentElement!.parentElement!;
  expect(sam.textContent).toContain("Quiet start: min 2 · recovered");
  expect(sam.textContent).toContain(
    "Quiet run starts at minute 2, labeled recovered.",
  );
  expect(sam.querySelector('svg line[x1="30"][x2="30"]')).not.toBeNull();
  expect(sam.querySelector("svg text")?.textContent).toBe("Min 2");
});

it("leaves silent minutes as chart gaps and keeps an unmeasured talk share unavailable", async () => {
  const silent: Transcript = {
    ...transcript,
    duration_ms: 180_000,
    segments: [
      { ...transcript.segments[0], start_ms: 0, end_ms: 10_000 },
      { ...transcript.segments[1], start_ms: 120_000, end_ms: 130_000 },
    ],
  };
  await act(async () =>
    root.render(
      <OverviewCallVisuals transcript={silent} onSeek={() => undefined} />,
    ),
  );
  expect(host.querySelectorAll("svg path")).toHaveLength(0);
  expect(host.querySelectorAll("svg circle")).toHaveLength(4);
  expect(host.textContent).not.toContain("Quiet start:");
  await act(async () =>
    root.render(
      <OverviewCallVisuals
        transcript={{
          ...transcript,
          duration_ms: 0,
          segments: [
            { ...transcript.segments[0], start_ms: 0, end_ms: 0, text: "" },
          ],
        }}
        onSeek={() => undefined}
      />,
    ),
  );
  expect(host.textContent).toContain("unavailable talk share");
  expect(host.textContent).not.toContain("%");
  expect(host.querySelectorAll("button")).toHaveLength(0);
});

it("computes overrun from the promise evidence time and preserves an unresolved measurement", async () => {
  const callMap = parseCallMap(
    fixture.call_map,
    fixture.segments,
    fixture.duration_ms,
  )!;
  const call: Transcript = {
    ...transcript,
    segments: fixture.segments,
    duration_ms: 660_000,
  };
  await act(async () =>
    root.render(
      <OverviewCallVisuals
        transcript={call}
        callMap={callMap}
        onSeek={() => undefined}
      />,
    ),
  );
  expect(host.textContent).toContain("Time promised10:00");
  expect(host.textContent).toContain("01:00 overrun");
  await act(async () =>
    root.render(
      <OverviewCallVisuals
        transcript={call}
        callMap={{ ...callMap, time_promise: null }}
        onSeek={() => undefined}
      />,
    ),
  );
  expect(host.textContent).toContain("Time promisedunavailable");
  expect(host.textContent).toContain("Computed overrununavailable");
  const missingPromiseSource = {
    ...callMap,
    time_promise: { ...callMap.time_promise!, evidence: [] },
  };
  await act(async () =>
    root.render(
      <OverviewCallVisuals
        transcript={call}
        callMap={missingPromiseSource}
        onSeek={() => undefined}
      />,
    ),
  );
  expect(host.textContent).toContain("Computed overrununavailable");
  expect(host.textContent).not.toContain("No overrun");
});
