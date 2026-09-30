import { describe, expect, it } from "vitest";
import fixture from "../tests/fixtures/call-record.json";
import {
  CallRecordContractError,
  parseCallRecord,
} from "./call-record-contract";

describe("call-record-contract", () => {
  it("parses the canonical fixture successfully", () => {
    const record = parseCallRecord(fixture);
    expect(record.version).toBe("call-record/1");
    expect(record.numbers.duration_ms).toBe(1320000);
    expect(record.numbers.speakers).toHaveLength(2);
    expect(record.numbers.overlaps).toBe(5);
    expect(record.facts).toHaveLength(4);
    expect(record.tags).toEqual([
      "People",
      "Business details",
      "Next steps and commitments",
      "Concerns",
    ]);
    expect(record.call_type).toBeNull();
  });

  it("permits tags and call_type to be null", () => {
    const withNulls = {
      ...fixture,
      tags: null,
      call_type: null,
    };
    const record = parseCallRecord(withNulls);
    expect(record.tags).toBeNull();
    expect(record.call_type).toBeNull();
  });

  it("drops facts that lack a quote or have empty evidence", () => {
    const withEmptyFact = {
      ...fixture,
      facts: [
        ...fixture.facts,
        {
          statement: "Fact with no evidence",
          evidence: [],
          tag: "Business details",
        },
      ],
    };
    const record = parseCallRecord(withEmptyFact);
    expect(record.facts).toHaveLength(4);
    expect(
      record.facts.find((f) => f.statement === "Fact with no evidence"),
    ).toBeUndefined();
  });

  it("rejects invalid contract version", () => {
    const invalid = {
      ...fixture,
      version: "call-record/2",
    };
    expect(() => parseCallRecord(invalid)).toThrow(CallRecordContractError);
  });

  it("rejects invalid speaker talk_share outside [0, 1]", () => {
    const invalid = {
      ...fixture,
      numbers: {
        ...fixture.numbers,
        speakers: [
          {
            ...fixture.numbers.speakers[0],
            talk_share: 1.5,
          },
        ],
      },
    };
    expect(() => parseCallRecord(invalid)).toThrow(CallRecordContractError);
  });
});
