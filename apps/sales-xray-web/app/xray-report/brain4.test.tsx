import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Transcript } from "../report-contract";
import { parseReportSettings, reportLook } from "../report-settings";
import { brain4Band, readBrain4 } from "./brain4";
import { Brain4Analysis } from "./brain4-view";
import { readStructure } from "./structure";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const transcript = {
  source_sha256: "a".repeat(64),
  revision: "r1",
  timebase_id: "t1",
  duration_ms: 20_000,
  segments: [
    {
      id: "s1",
      speaker_id: "speaker_0",
      start_ms: 0,
      end_ms: 5_000,
      text: "What happens to a lead after it comes in?",
    },
  ],
} as Transcript;

const quote = {
  segment_id: "s1",
  quote: "What happens to a lead after it comes in?",
  start_ms: 0,
  end_ms: 5_000,
};

const IDS = Array.from(
  { length: 18 },
  (_, i) => `D${String(i + 1).padStart(2, "0")}`,
);

function block(extra: Record<string, unknown> = {}) {
  return {
    version: "brain4-review/1",
    status: "beta",
    calibration: { revision: "brain4-calibration/0", label: "beta" },
    dimensions: IDS.map((id, index) => ({
      id,
      number: index + 1,
      label: `Skill ${index + 1}`,
      category: index < 7 ? "how_you_talk" : "moving_the_sale_forward",
      rating: id === "D03" ? null : 4,
      shown_rating: id === "D04" ? 3 : id === "D03" ? null : 4,
      applicability: id === "D03" ? "not_enough_evidence" : "applicable",
      observed: "You asked what happens next.",
      coaching: id === "D03" ? "ignored when not rated" : "Ask why next.",
      ethics_gate: id === "D07" ? "WARN" : null,
      evidence: [quote, { ...quote, segment_id: "s9" }],
    })),
    rollup: {
      method: "category_mean",
      categories: [
        {
          id: "how_you_talk",
          label: "How You Talk",
          rated: 6,
          of: 7,
          score: 3.8,
        },
      ],
    },
    ...extra,
  };
}

const evidence = (value: unknown) =>
  Array.isArray(value)
    ? value.filter((item) => item.segment_id === "s1").slice(0, 6)
    : [];

describe("Brain 4.0 in the Report", () => {
  it("reads the saved block: calibrated ratings, '–' for unrated, the ethics gate", () => {
    const view = readBrain4(block(), evidence)!;
    expect(view.dimensions).toHaveLength(18);
    const byId = Object.fromEntries(view.dimensions.map((d) => [d.id, d]));
    expect(byId.D04.rating).toBe(3);
    expect(byId.D03.rating).toBeNull();
    expect(byId.D03.coaching).toBeNull();
    expect(byId.D03.applicability).toBe("not_enough_evidence");
    expect(byId.D01.evidence).toHaveLength(1);
    expect(view.ethicsGate).toBe("WARN");
    expect(view.calibration).toBe("brain4-calibration/0");
    expect(view.categories[0]).toMatchObject({ rated: 6, score: 3.8 });
  });

  it("shows nothing that is not a beta Brain 4.0 block", () => {
    expect(readBrain4(null, evidence)).toBeNull();
    expect(readBrain4(block({ status: "official" }), evidence)).toBeNull();
    expect(readBrain4(block({ version: "other/1" }), evidence)).toBeNull();
    expect(readBrain4(block({ dimensions: [] }), evidence)).toBeNull();
  });

  it("comes through the report structure", () => {
    const view = readStructure(
      { version: "report-structure/1", overview: {}, brain4: block() },
      transcript,
      "speaker_0",
      "speaker_1",
    );
    expect(view?.brain4?.dimensions).toHaveLength(18);
    expect(
      readStructure(
        { version: "report-structure/1", overview: {} },
        transcript,
        null,
        null,
      )?.brain4,
    ).toBeNull();
  });

  it("is chosen per organisation by its report settings version", () => {
    const look = (report: Record<string, unknown>) =>
      reportLook(
        parseReportSettings({
          version: { number: 5 },
          source: "organisation",
          settings: { report },
        }),
      );
    expect(look({ scoring: "brain4_beta" }).scoring).toBe("brain4_beta");
    expect(look({ scoring: "nonsense" }).scoring).toBe("classic");
    expect(reportLook(parseReportSettings({})).scoring).toBe("classic");
  });

  it("maps ratings onto the Report's bands", () => {
    expect([5, 4, 3, 2, 1, null].map(brain4Band)).toEqual([
      "excellent",
      "good",
      "average",
      "needs_improvement",
      "needs_improvement",
      null,
    ]);
  });
});

describe("the Brain 4.0 section", () => {
  let host: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  it("lists the 18 skills with a Beta label and opens one", async () => {
    const view = readBrain4(block(), evidence)!;
    await act(async () => root.render(<Brain4Analysis view={view} />));
    const rows = host.querySelectorAll("[data-brain4]");
    expect(rows).toHaveLength(18);
    expect(host.textContent).toContain("Beta");
    expect(host.textContent).toContain("3.8 / 5");
    expect(host.textContent).toContain("Not enough evidence");
    const first = rows[3].querySelector("button")!;
    expect(first.getAttribute("aria-label")).toContain("3 out of 5, beta");
    await act(async () => first.click());
    expect(host.textContent).toContain("On Your Next Call");
    expect(host.textContent).toContain("What happens to a lead");
  });
});
