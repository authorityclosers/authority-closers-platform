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
  normalizeTranscription,
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

  it("reads the transcription route and the Gemini configuration's state", () => {
    const view = normalizeTranscription({
      latest_revision: 7,
      sealed_bundle: "f".repeat(64),
      active: {
        revision: 6,
        configuration_sha256: "a".repeat(64),
        transcription: { provider: "elevenlabs", model: "scribe_v2" },
        one_pass: false,
      },
      gemini: {
        model: "gemini-3.1-flash-lite",
        profile_id: "gemini-flash-lite-c2",
        configuration_sha256: "b".repeat(64),
        saved_revision: 7,
        approved: true,
      },
      gemini_flex: {
        model: "gemini-3.1-flash-lite:flex",
        profile_id: "gemini-flash-lite-c2-flex",
        configuration_sha256: "c".repeat(64),
        saved_revision: null,
        approved: false,
      },
      one_pass: {
        model: "gemini-3.1-flash-lite",
        profile_id: "gemini-one-pass",
        configuration_sha256: "d".repeat(64),
        saved_revision: 8,
        approved: false,
      },
      classic_revision: 6,
      confirm: "one_pass",
    });
    expect(view.active).toMatchObject({
      revision: 6,
      provider: "elevenlabs",
      flex: false,
    });
    expect(view.gemini).toMatchObject({ savedRevision: 7, approved: true });
    expect(view.geminiFlex).toMatchObject({
      profileId: "gemini-flash-lite-c2-flex",
      savedRevision: null,
      approved: false,
    });
    expect(view.onePass).toMatchObject({
      profileId: "gemini-one-pass",
      savedRevision: 8,
      approved: false,
    });
    expect(view.onePassFlex.savedRevision).toBeNull();
    expect(view.active?.onePass).toBe(false);
    expect(view.classicRevision).toBe(6);
    const empty = normalizeTranscription(null);
    expect(empty.active).toBeNull();
    expect(empty.gemini.savedRevision).toBeNull();
    expect(empty.gemini.approved).toBe(false);
    expect(empty.confirm).toBe("one_pass");
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
