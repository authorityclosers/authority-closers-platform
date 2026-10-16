import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchCoaching,
  parseCoaching,
  shownCallLabel,
} from "./coaching-client";
import { fictionalCoaching } from "./coaching.fixture";

afterEach(() => vi.unstubAllGlobals());
describe("private Coaching contract", () => {
  it("accepts unknown mastery without inventing execution percentages", () => {
    const result = parseCoaching(structuredClone(fictionalCoaching));
    expect(result.mastery.correct_count).toBeNull();
    expect(result.evidence).toHaveLength(2);
  });
  it("rejects crossed mission identity, wrong authority and invalid audio spans", () => {
    const data = structuredClone(fictionalCoaching);
    data.mission!.skill_id = "qualification";
    expect(() => parseCoaching(data)).toThrow();
    expect(() =>
      parseCoaching({ ...fictionalCoaching, authority: "official" }),
    ).toThrow();
    const timing = structuredClone(fictionalCoaching);
    timing.evidence[0].end_ms = 500;
    expect(() => parseCoaching(timing)).toThrow();
  });
  it("rejects unreviewed media and mismatched success counts", () => {
    expect(() =>
      parseCoaching({
        ...fictionalCoaching,
        recommended_media: { url: "javascript:alert(1)" },
      }),
    ).toThrow();
    const data = structuredClone(fictionalCoaching);
    data.mastery.correct_count = 5;
    data.mastery.relevant_count = 2;
    expect(() => parseCoaching(data)).toThrow();
  });
  it("keeps a quoted strength and drops a malformed one without failing", () => {
    const moment = fictionalCoaching.evidence[0];
    const strength = {
      title: "Asked a follow-up",
      explanation: "It made the problem specific.",
      evidence: [moment],
    };
    expect(parseCoaching({ ...fictionalCoaching, strength }).strength).toEqual(
      strength,
    );
    for (const bad of [
      { ...strength, evidence: [{ ...moment, end_ms: 1 }] },
      { ...strength, title: "" },
      { ...strength, evidence: [] },
      null,
    ]) {
      const parsed = parseCoaching({ ...fictionalCoaching, strength: bad });
      expect(parsed.focus?.label).toBe(fictionalCoaching.focus?.label);
      expect(parsed.strength).toBeNull();
    }
  });
  it("uses the same-origin account with no cache or caller identity selectors", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fictionalCoaching), {
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const signal = new AbortController().signal;
    await fetchCoaching(signal);
    expect(fetch).toHaveBeenCalledWith(
      "/v1/me/coaching",
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
        signal,
      }),
    );
  });
  it("does not expose an arbitrary server error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("private backend diagnostic", { status: 500 }),
        ),
    );
    await expect(fetchCoaching(new AbortController().signal)).rejects.toThrow(
      "Coaching didn’t load. Try again.",
    );
  });
});

describe("call names in Coaching", () => {
  it("never shows an internal transcript id as a call's name", () => {
    const internal =
      "Scribe transcript revision 1310ab5efc17fc169bf932e617705f9dd0c5d0f427963728c275a8cfa269bc43 · source-bound";
    expect(shownCallLabel(internal, "2026-09-30T10:00:00Z")).toMatch(
      /^Sales call · /,
    );
    expect(shownCallLabel(internal)).toBe("Sales call");
    expect(shownCallLabel("Ankita · discovery call")).toBe(
      "Ankita · discovery call",
    );
  });
});
