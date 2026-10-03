import { describe, expect, it } from "vitest";
import vectorFile from "../tests/fixtures/call-type-vectors.json";
import {
  CALL_TYPE_THRESHOLDS,
  CALL_TYPES,
  deriveCallType,
  type CallTypeInput,
} from "./call-type";

type Rows = {
  phases?: [string, number][];
  objection_spans?: [number, number][];
};
type Vector = {
  name: string;
  input: Omit<Partial<CallTypeInput>, keyof Rows> & Rows;
  expected: string;
};

// Vector inputs override the base; phase and span rows become objects.
const toInput = (overrides: Vector["input"]): CallTypeInput => {
  const merged = { ...vectorFile.base, ...overrides } as Required<Rows> &
    Omit<CallTypeInput, keyof Rows>;
  return {
    ...merged,
    phases: merged.phases.map(([name, start_ms]) => ({ name, start_ms })),
    objection_spans: merged.objection_spans.map(([start_ms, end_ms]) => ({
      start_ms,
      end_ms,
    })),
  };
};

const vectors = (vectorFile.vectors as unknown as Vector[]).map((vector) => ({
  ...vector,
  input: toInput(vector.input),
}));
const full = toInput({});

describe("call type shared vectors (AUT-629)", () => {
  it.each(vectors.map((vector) => [vector.name, vector] as const))(
    "%s",
    (_name, vector) => {
      expect(deriveCallType(vector.input)).toBe(vector.expected);
    },
  );

  it("pins the proposed thresholds to the vectors", () => {
    expect(CALL_TYPE_THRESHOLDS).toEqual(vectorFile.thresholds);
  });

  it("covers every type and unclear", () => {
    const seen = new Set(vectors.map((vector) => vector.expected));
    expect([...seen].sort()).toEqual([...CALL_TYPES, "unclear"].sort());
  });
});

describe("call type rule", () => {
  it.each([
    ["duration", { duration_ms: Number.POSITIVE_INFINITY }],
    ["share", { prospect_talk_share: Number.NaN }],
    ["phase start", { phases: [{ name: "discovery", start_ms: Number.NaN }] }],
    [
      "objection span",
      {
        objection_spans: [{ start_ms: 0, end_ms: Number.POSITIVE_INFINITY }],
      },
    ],
  ])("returns unclear for a non-finite %s", (_name, change) => {
    expect(deriveCallType({ ...full, ...change } as CallTypeInput)).toBe(
      "unclear",
    );
  });

  it("returns only closed keys, never a number", () => {
    for (const vector of vectors)
      expect(typeof deriveCallType(vector.input)).toBe("string");
  });
});
