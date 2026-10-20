import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  ReportLookContext,
  VERSION_1_LOOK,
  lookPointers,
  parseReportSettings,
  reportLook,
  type ReportLook,
} from "../report-settings";
import { unscoredPointers, type Pointer } from "./model";
import { CallAnalysis } from "./pointers";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

/** A published version (Admin → Report settings), as the server sends it. */
const published = (report: Record<string, unknown>, extra = {}) =>
  reportLook(
    parseReportSettings({
      version: { number: 4, label: "Short" },
      source: "industry",
      settings: { report, ...extra },
    }),
  );

describe("the look a report settings version asks for", () => {
  it("is today's look for version 1, whatever its document says", () => {
    expect(reportLook(parseReportSettings({}))).toBe(VERSION_1_LOOK);
    expect(
      reportLook(
        parseReportSettings({
          version: { number: 1 },
          settings: { report: { style: "scorecard", show_scores: false } },
        }),
      ),
    ).toBe(VERSION_1_LOOK);
  });

  it("reads style, detail, pointers, the cap, scores, quotes and tips", () => {
    const look = published({
      style: "compact",
      complexity: "simple",
      pointers: ["next_steps", "call_opening"],
      max_pointers: 3,
      show_scores: false,
      show_evidence: true,
      show_how_to_improve: true,
    });
    expect(look).toMatchObject({
      version: 4,
      style: "compact",
      detail: "simple",
      pointers: ["next_steps", "call_opening"],
      maxPointers: 3,
      scores: false,
      // The simple detail never shows quotes or tips.
      evidence: false,
      tips: false,
    });
    // All 27 is no limit; nonsense falls back to today's choice.
    expect(published({ max_pointers: 27, style: "fancy" })).toMatchObject({
      maxPointers: null,
      style: "guided",
    });
  });

  it("reads the Prospect sections and the Coaching moments", () => {
    const look = published(
      {},
      {
        prospect: {
          complexity: "simple",
          sections: { quality: false, buyer_info: false },
          show_inferred: false,
        },
        coaching: {
          show_moments: true,
          max_moments: 2,
          show_across_calls: false,
        },
      },
    );
    expect(look.prospect.sections).toMatchObject({
      quality: false,
      buyer_info: false,
      problem: true,
    });
    expect(look.prospect).toMatchObject({ detail: "simple", inferred: false });
    expect(look.coaching).toMatchObject({
      moments: true,
      maxMoments: 2,
      acrossCalls: false,
    });
  });

  it("lists the chosen pointers in the version's order, or all of them", () => {
    const all = unscoredPointers();
    expect(lookPointers(all, VERSION_1_LOOK)).toHaveLength(27);
    expect(
      lookPointers(all, { pointers: ["pricing", "call_opening"] }).map(
        (pointer) => pointer.id,
      ),
    ).toEqual(["pricing", "call_opening"]);
    // A version naming no pointer this Report has keeps them all.
    expect(lookPointers(all, { pointers: ["gone"] })).toHaveLength(27);
  });
});

let root: Root;
let host: HTMLDivElement;
const scored: Pointer[] = unscoredPointers().map((pointer, index) => ({
  ...pointer,
  status: index % 2 ? "good" : "needs_improvement",
  score: 40 + index,
  whatHappened: `What happened at ${pointer.name}`,
  whyItMatters: "Why it matters",
  evidence: [],
  howToImprove: ["One tip"],
}));

async function show(look: ReportLook) {
  await act(async () =>
    root.render(
      <ReportLookContext.Provider value={look}>
        <CallAnalysis pointers={scored} illustrative={false} />
      </ReportLookContext.Provider>,
    ),
  );
}
const rows = () =>
  [...host.querySelectorAll<HTMLElement>("[data-pointer]")].map(
    (row) => row.dataset.pointer,
  );
const button = (text: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("the Detailed Call Analysis under a version", () => {
  it("is today's table in version 1", async () => {
    await show(VERSION_1_LOOK);
    expect(rows()).toHaveLength(27);
    const part = host.querySelector("[data-xray-part='analysis']")!;
    expect(part.hasAttribute("data-style")).toBe(false);
    expect(part.hasAttribute("data-scores")).toBe(false);
    expect(button("Show all")).toBeUndefined();
  });

  it("lists the version's pointers, the first few, then Show all", async () => {
    await show({
      ...VERSION_1_LOOK,
      version: 4,
      pointers: ["pricing", "next_steps", "call_opening", "objections"],
      maxPointers: 3,
    });
    expect(rows()).toEqual(["pricing", "next_steps", "call_opening"]);
    await act(async () => button("Show all 4 pointers")!.click());
    expect(rows()).toEqual([
      "pricing",
      "next_steps",
      "call_opening",
      "objections",
    ]);
  });

  it("names no score when the version hides scores", async () => {
    await show({ ...VERSION_1_LOOK, version: 4, scores: false });
    const first = host.querySelector("[data-pointer] button")!;
    expect(first.getAttribute("aria-label")).not.toContain("out of 100");
    expect(
      host
        .querySelector("[data-xray-part='analysis']")!
        .getAttribute("data-scores"),
    ).toBe("off");
  });

  it("opens a compact pointer to what happened only", async () => {
    await show({ ...VERSION_1_LOOK, version: 4, style: "compact" });
    await act(async () =>
      host.querySelector<HTMLButtonElement>("[data-pointer] button")!.click(),
    );
    expect(host.textContent).toContain("What Happened?");
    expect(host.textContent).not.toContain("Why It Matters?");
    expect(host.textContent).not.toContain("How to Improve?");
  });

  it("lays a scorecard out as tiles, each opening its detail", async () => {
    await show({ ...VERSION_1_LOOK, version: 4, style: "scorecard" });
    expect(host.querySelector("ol li[data-pointer]")).not.toBeNull();
    expect(host.textContent).not.toContain("What This Evaluates");
    const tile = host.querySelector<HTMLButtonElement>(
      "[data-pointer='pricing'] button",
    )!;
    await act(async () => tile.click());
    expect(tile.getAttribute("aria-expanded")).toBe("true");
    expect(host.textContent).toContain("What happened at");
  });
});
