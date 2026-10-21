import { describe, expect, it } from "vitest";

import {
  fixtureCompared,
  fixtureList,
  fixturePipeline,
} from "../review-fixture/one-pass/one-pass-fixture";
import {
  inr,
  normalizeCompareList,
  normalizeCompared,
  normalizePipeline,
  share,
  took,
} from "./one-pass-data";

describe("one-pass trial data", () => {
  it("reads the switch with every choice and why it is off", () => {
    const settings = normalizePipeline(fixturePipeline);
    expect(settings.mode).toBe("both");
    expect(settings.revision).toBe(2);
    expect(
      settings.modes.map((m) => [m.value, Boolean(m.whyNot), m.needsOwner]),
    ).toEqual([
      ["classic", false, false],
      ["both", false, false],
      ["one_pass", false, true],
    ]);
    expect(settings.confirm).toBe("one_pass");
    expect(settings.models.analysis).toBe("gemini-3.8-flash");
    expect(settings.recent[0]).toMatchObject({
      subject: "fx-01",
      contractsOk: 6,
    });
  });

  it("never crashes on an empty or odd answer", () => {
    const settings = normalizePipeline(null);
    expect(settings).toMatchObject({
      mode: "classic",
      revision: null,
      modes: [],
    });
    const list = normalizeCompareList({
      summary: { calls: "x" },
      items: [1, null],
    });
    expect(list.calls.calls).toBe(0);
    expect(list.items).toHaveLength(2);
    expect(list.items[0].kind).toBe("call");
    const one = normalizeCompared({});
    expect(one.classic).toBeNull();
    expect(one.onePass).toBeNull();
    expect(one.facts).toBeNull();
  });

  it("reads the summary and the list", () => {
    const list = normalizeCompareList(fixtureList);
    expect(list.bench.onePass.flexPerMinuteInr).toBe(0.2);
    expect(list.bench.classic.factRecall).toBe(0.706);
    expect(list.bench.agreement.pointerStatus).toBe(0.63);
    expect(list.items[0]).toMatchObject({
      kind: "bench",
      subject: "fx-01",
      onePass: { contractsOk: 6, flexCostInr: 0.7 },
    });
  });

  it("reads one call side by side", () => {
    const data = normalizeCompared(fixtureCompared);
    expect(data.kind).toBe("bench");
    expect(data.onePass?.stages.map((s) => s.key)).toEqual([
      "transcription",
      "analysis",
    ]);
    expect(data.classic?.stages).toHaveLength(6);
    expect(data.onePass?.checks?.c5).toBe("ok");
    expect(data.facts?.onlyOnePass[0].display).toBe("Pune");
    expect(data.pointers?.rows[1]).toMatchObject({
      same: false,
      onePass: { score: 62 },
    });
    expect(data.dimensions[1]).toEqual({
      id: "qualification",
      classic: "observed",
      onePass: "insufficient_evidence",
    });
  });

  it("formats rupees, shares and times", () => {
    expect(inr(1.194)).toBe("₹1.19");
    expect(inr(null)).toBe("");
    expect(share(0.734)).toBe("73%");
    expect(share(null)).toBe("—");
    expect(took(42_400)).toBe("42 s");
    expect(took(65_000)).toBe("1 min 05 s");
    expect(took(null)).toBe("—");
  });
});
