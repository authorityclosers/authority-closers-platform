import { afterEach, describe, expect, it, vi } from "vitest";
import {
  parseCallCoaching,
  readCoaching,
  requestedCall,
} from "./coaching-read";
import { fictionalCallCoaching } from "./coaching.fixture";

const callId = fictionalCallCoaching.submission_id;
afterEach(() => vi.unstubAllGlobals());
describe("call-specific coaching read", () => {
  it("keeps one call's identity, evidence and mission", () => {
    const parsed = parseCallCoaching(fictionalCallCoaching, callId)!;
    expect(parsed.evidence).toHaveLength(1);
    expect(parsed.mission?.origin_submission_id).toBe(callId);
    expect(parsed.lesson?.own_call?.submission_id).toBe(callId);
  });
  it("defaults missing optional fields without a page crash", () => {
    const raw = {
      ...fictionalCallCoaching,
      evidence: undefined,
      root_cause: undefined,
      limitations: undefined,
      practice: undefined,
      lesson: {
        ...fictionalCallCoaching.lesson,
        framework: undefined,
        checklist: undefined,
        own_call: null,
        when_not: undefined,
      },
    };
    const parsed = parseCallCoaching(raw, callId)!;
    expect(parsed.evidence).toEqual([]);
    expect(parsed.root_cause.gap_type).toBe("uncertain");
    expect(parsed.practice?.exercise).toContain("rehearse");
    expect(parsed.lesson?.framework).toEqual([]);
    expect(parsed.lesson?.when_not).toContain("boundary");
  });
  it("keeps a quoted strength and drops a malformed or foreign one alone", () => {
    const moment = fictionalCallCoaching.evidence[0];
    const strength = {
      title: "Asked for a consequence",
      explanation: "It made the problem specific.",
      evidence: [moment],
    };
    const kept = parseCallCoaching(
      { ...fictionalCallCoaching, strength },
      callId,
    )!;
    expect(kept.strength?.title).toBe("Asked for a consequence");
    expect(kept.strength?.evidence[0].submission_id).toBe(callId);
    for (const bad of [
      { ...strength, evidence: [] },
      { ...strength, title: "" },
      {
        ...strength,
        evidence: [{ ...moment, source_sha256: "b".repeat(64) }],
      },
      "not an object",
    ]) {
      const parsed = parseCallCoaching(
        { ...fictionalCallCoaching, strength: bad },
        callId,
      );
      expect(parsed?.focus?.label).toBe(fictionalCallCoaching.focus?.label);
      expect(parsed?.strength).toBeNull();
    }
    expect(
      parseCallCoaching(fictionalCallCoaching, callId)?.strength,
    ).toBeNull();
  });
  it("rejects crossed call/mission/lesson sources and unparsed media", () => {
    for (const raw of [
      {
        ...fictionalCallCoaching,
        submission_id: "00000000-0000-0000-0000-000000000099",
      },
      { ...fictionalCallCoaching, authority: "official" },
      {
        ...fictionalCallCoaching,
        mission: {
          ...fictionalCallCoaching.mission,
          origin_submission_id: "00000000-0000-0000-0000-000000000099",
        },
      },
      {
        ...fictionalCallCoaching,
        evidence: [
          {
            ...fictionalCallCoaching.evidence[0],
            source_sha256: "c".repeat(64),
          },
        ],
      },
      {
        ...fictionalCallCoaching,
        lesson: {
          ...fictionalCallCoaching.lesson,
          own_call: {
            ...fictionalCallCoaching.evidence[0],
            recording_id: "00000000-0000-0000-0000-000000000099",
          },
        },
      },
      {
        ...fictionalCallCoaching,
        recommended_media: { url: "javascript:alert(1)" },
      },
    ])
      expect(parseCallCoaching(raw, callId)).toBeNull();
  });
  it("makes one selected-call request with no cache and returns network failures", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fictionalCallCoaching), {
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    expect((await readCoaching(callId)).data?.schema).toBe(
      "ac.sales-xray.call-coaching/1",
    );
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith(
      `/v1/me/coaching/calls/${callId}`,
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
      }),
    );
    fetch.mockRejectedValue(new Error("private diagnostic"));
    expect(await readCoaching(callId)).toEqual({
      data: null,
      error: "Coaching could not be loaded. Try again.",
    });
  });
  it("does not send malformed call selectors or expose missing-route diagnostics", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    for (const value of [
      "../someone",
      "",
      "https://example.test",
      [callId],
      undefined,
    ])
      expect(requestedCall(value)).toBeNull();
    await readCoaching("../someone");
    expect(fetch).not.toHaveBeenCalled();
    fetch.mockResolvedValue(
      new Response("private upstream text", { status: 404 }),
    );
    const result = await readCoaching(callId);
    expect(result.data).toBeNull();
    expect(result.error).toContain("Open the call");
    expect(result.error).not.toContain("private upstream");
  });
});
