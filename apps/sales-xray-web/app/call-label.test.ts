import { describe, expect, it } from "vitest";
import {
  CallLabelContractError,
  callLabelEtag,
  callTitle,
  parseCallLabel,
  validateCallLabel,
} from "./call-label";

describe("call label contract (C1)", () => {
  it("treats both fields absent as an older server without labels", () => {
    expect(parseCallLabel({ state: "completed" })).toBeNull();
  });

  it("reads a saved name, a cleared name and the unnamed initial state", () => {
    expect(
      parseCallLabel({
        display_name: "Harbolite discovery",
        display_name_revision: 2,
      }),
    ).toEqual({ displayName: "Harbolite discovery", revision: 2 });
    expect(
      parseCallLabel({ display_name: null, display_name_revision: 3 }),
    ).toEqual({ displayName: null, revision: 3 });
    expect(
      parseCallLabel({ display_name: null, display_name_revision: 0 }),
    ).toEqual({ displayName: null, revision: 0 });
  });

  it("rejects half-present, mistyped or impossible labels", () => {
    const bad = [
      { display_name: "Only a name" },
      { display_name_revision: 1 },
      { display_name: 5, display_name_revision: 1 },
      { display_name: "x", display_name_revision: -1 },
      { display_name: "x", display_name_revision: 1.5 },
      { display_name: "   ", display_name_revision: 1 },
      { display_name: "Named at zero", display_name_revision: 0 },
      { display_name: "a".repeat(121), display_name_revision: 1 },
    ];
    for (const value of bad)
      expect(() => parseCallLabel(value)).toThrow(CallLabelContractError);
  });

  it("formats the strong entity tag the rename endpoint requires", () => {
    expect(callLabelEtag(0)).toBe('"call-label-0"');
    expect(callLabelEtag(12)).toBe('"call-label-12"');
  });

  it("mirrors the server's trim, control and 120 code-point rules", () => {
    expect(validateCallLabel("  Budget follow-up  ")).toEqual({
      ok: true,
      name: "Budget follow-up",
    });
    expect(validateCallLabel("   ").ok).toBe(false);
    expect(validateCallLabel("line\nbreak").ok).toBe(false);
    expect(validateCallLabel("tab\there").ok).toBe(false);
    // 120 emoji are 240 UTF-16 units but exactly 120 code points: accepted.
    expect(validateCallLabel("😀".repeat(120)).ok).toBe(true);
    expect(validateCallLabel("😀".repeat(121)).ok).toBe(false);
    // Devanagari names are accepted as written.
    expect(validateCallLabel("हार्बोलाइट कॉल").ok).toBe(true);
  });

  it("falls back honestly when no name is saved", () => {
    expect(callTitle(null, "Sales call · 25 Sep 2026")).toBe(
      "Sales call · 25 Sep 2026",
    );
    expect(
      callTitle({ displayName: null, revision: 2 }, "Sales call report"),
    ).toBe("Sales call report");
    expect(
      callTitle({ displayName: "Renewal", revision: 3 }, "Sales call report"),
    ).toBe("Renewal");
  });
});
