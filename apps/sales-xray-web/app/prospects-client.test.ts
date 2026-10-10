import { describe, expect, it, vi } from "vitest";

import {
  confirmDetectedProspect,
  fetchProspectDetail,
  fetchProspectsList,
  parseProspectCall,
  parseProspectCallSnapshot,
  parseProspectDetail,
  parseProspectListPage,
  parseProspectSummary,
  ProspectsContractError,
  PROSPECTS_API,
} from "./prospects-client";

it("requires the same prospect and a persisted confirmation receipt", async () => {
  const id = "11111111-1111-4111-8111-111111111111";
  const receipt = {
    schema: "ac.sales-xray.prospect-confirmation/1",
    prospect_id: id,
    revision: 3,
    confirmed_at: "2026-10-10T08:00:00Z",
  };
  const fetch = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(receipt)));
  vi.stubGlobal("fetch", fetch);
  try {
    await confirmDetectedProspect(id, 2);
    expect(fetch).toHaveBeenCalledWith(
      `${PROSPECTS_API}/${id}/confirm`,
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        redirect: "error",
        body: JSON.stringify({ expected_revision: 2 }),
      }),
    );
    for (const value of [
      { ...receipt, prospect_id: "22222222-2222-4222-8222-222222222222" },
      { ...receipt, revision: 1 },
      { ...receipt, confirmed_at: null },
    ]) {
      fetch.mockResolvedValueOnce(new Response(JSON.stringify(value)));
      await expect(confirmDetectedProspect(id, 2)).rejects.toThrow(
        "confirmation_response",
      );
    }
    fetch.mockResolvedValueOnce(new Response("{}", { status: 409 }));
    await expect(confirmDetectedProspect(id, 2)).rejects.toThrow(
      "Reload before confirming",
    );
  } finally {
    vi.unstubAllGlobals();
  }
});

describe("prospects-client contract parsers", () => {
  const validSummary = {
    prospect_id: "11111111-1111-4111-8111-111111111111",
    name: "Snapshot Example",
    revision: 1,
    owner_person_id: "22222222-2222-4222-8222-222222222222",
    stage: null,
    tags: [],
    photo_url: null,
    contact: null,
    fields: [],
    buyer_intent: null,
    next_step: null,
    last_promise: null,
    call_count: 1,
    last_call: "2026-10-05T00:00:00+00:00",
  };

  const validSnapshot = {
    snapshot_id: "55555555-5555-4555-8555-555555555555",
    snapshot_kind: "c5_checkpoint",
    source_revision: 1,
    source_sha256:
      "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    run_id: null,
    transcript_revision: "scribe-response-r1",
    review_status: "draft_not_dipak_adjudicated",
    interpretations: [
      {
        source: {
          text: "The buyer asks about timing.",
          evidence: [
            {
              segment_id: "s1",
              quote: "the buyer asks about price and timing.",
              start_ms: 0,
              end_ms: 900,
            },
          ],
        },
        possible_concern: "The buyer may need more time.",
        interpretation_kind: "inference",
      },
    ],
  };

  const validCall = {
    submission_id: "33333333-3333-4333-8333-333333333333",
    recording_id: "44444444-4444-4444-8444-444444444444",
    created_at: "2026-10-05T00:00:00+00:00",
    duration_seconds: 120,
    display_name: "Initial Discovery Call",
    state: "report_ready",
    has_report: true,
    score: null,
    call_url: "/analysis/calls/33333333-3333-4333-8333-333333333333",
    report_url: "/analysis/calls/33333333-3333-4333-8333-333333333333",
    snapshot: validSnapshot,
  };

  it("parses valid prospect summary with null fields preserved", () => {
    const parsed = parseProspectSummary(validSummary);
    expect(parsed.prospect_id).toBe("11111111-1111-4111-8111-111111111111");
    expect(parsed.name).toBe("Snapshot Example");
    expect(parsed.stage).toBeNull();
    expect(parsed.tags).toEqual([]);
    expect(parsed.photo_url).toBeNull();
    expect(parsed.contact).toBeNull();
    expect(parsed.fields).toEqual([]);
    expect(parsed.buyer_intent).toBeNull();
    expect(parsed.next_step).toBeNull();
    expect(parsed.last_promise).toBeNull();
    expect(parsed.call_count).toBe(1);
    expect(parsed.last_call).toBe("2026-10-05T00:00:00+00:00");
  });

  it("rejects invalid prospect summary UUID", () => {
    expect(() =>
      parseProspectSummary({ ...validSummary, prospect_id: "invalid-uuid" }),
    ).toThrow(ProspectsContractError);
  });

  it("parses valid prospect list page", () => {
    const listPayload = {
      schema: "ac.sales-xray.prospects/1",
      prospects: [validSummary],
      total: 1,
      stage_filters: [],
      next_offset: null,
    };
    const parsed = parseProspectListPage(listPayload);
    expect(parsed.schema).toBe("ac.sales-xray.prospects/1");
    expect(parsed.prospects).toHaveLength(1);
    expect(parsed.total).toBe(1);
    expect(parsed.stage_filters).toEqual([]);
    expect(parsed.next_offset).toBeNull();
  });

  it("parses pagination with next_offset", () => {
    const listPayload = {
      schema: "ac.sales-xray.prospects/1",
      prospects: [validSummary],
      total: 42,
      stage_filters: [],
      next_offset: 20,
    };
    const parsed = parseProspectListPage(listPayload);
    expect(parsed.next_offset).toBe(20);
    expect(parsed.total).toBe(42);
  });

  it("parses call snapshot with provenance and interpretations", () => {
    const snapshot = parseProspectCallSnapshot(validSnapshot);
    expect(snapshot).not.toBeNull();
    expect(snapshot?.snapshot_kind).toBe("c5_checkpoint");
    expect(snapshot?.source_revision).toBe(1);
    expect(snapshot?.interpretations).toHaveLength(1);
    expect(snapshot?.interpretations[0].interpretation_kind).toBe("inference");
    expect(snapshot?.interpretations[0].source.evidence[0].quote).toBe(
      "the buyer asks about price and timing.",
    );
  });

  it("returns null for absent call snapshot", () => {
    expect(parseProspectCallSnapshot(null)).toBeNull();
    expect(parseProspectCallSnapshot(undefined)).toBeNull();
  });

  it("parses call and enforces null score", () => {
    const call = parseProspectCall(validCall);
    expect(call.submission_id).toBe("33333333-3333-4333-8333-333333333333");
    expect(call.score).toBeNull();
    expect(call.has_report).toBe(true);
    expect(call.report_url).toBe(
      "/analysis/calls/33333333-3333-4333-8333-333333333333",
    );
  });

  it("rejects non-null call score", () => {
    expect(() => parseProspectCall({ ...validCall, score: 85 })).toThrow(
      ProspectsContractError,
    );
  });

  it("parses prospect detail with calls", () => {
    const detailPayload = {
      schema: "ac.sales-xray.prospects/1",
      prospect: validSummary,
      calls: [validCall],
      next_offset: null,
      promises: [],
      next_steps: [],
      buyer_intent_history: [],
    };
    const parsed = parseProspectDetail(detailPayload);
    expect(parsed.prospect.name).toBe("Snapshot Example");
    expect(parsed.calls).toHaveLength(1);
    expect(parsed.calls[0].snapshot).not.toBeNull();
    expect(parsed.promises).toEqual([]);
    expect(parsed.next_steps).toEqual([]);
    expect(parsed.buyer_intent_history).toEqual([]);
  });
});

describe("prospects-client fetchers", () => {
  it("fetches prospects list with search and stage parameters", async () => {
    const mockResponse = {
      schema: "ac.sales-xray.prospects/1",
      prospects: [],
      total: 0,
      stage_filters: [],
      next_offset: null,
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => mockResponse,
    } as Response);

    const result = await fetchProspectsList({
      search: "Acme",
      stage: "__missing__",
      offset: 20,
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      `${PROSPECTS_API}?search=Acme&stage=__missing__&offset=20`,
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
    expect(result.total).toBe(0);
    fetchSpy.mockRestore();
  });

  it("handles 401 unauthenticated response gracefully", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Sign in to read your prospects." }),
    } as Response);

    await expect(fetchProspectsList()).rejects.toThrow(
      "Sign in to read your prospects.",
    );
    fetchSpy.mockRestore();
  });

  it("handles 403 workspace unavailable gracefully", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Workspace unavailable." }),
    } as Response);

    await expect(fetchProspectsList()).rejects.toThrow(
      "Workspace unavailable.",
    );
    fetchSpy.mockRestore();
  });

  it("fetches prospect detail and validates id", async () => {
    const mockDetail = {
      schema: "ac.sales-xray.prospects/1",
      prospect: {
        prospect_id: "11111111-1111-4111-8111-111111111111",
        name: "Test Person",
        revision: 1,
        owner_person_id: "22222222-2222-4222-8222-222222222222",
        stage: null,
        tags: [],
        photo_url: null,
        contact: null,
        fields: [],
        buyer_intent: null,
        next_step: null,
        last_promise: null,
        call_count: 0,
        last_call: null,
      },
      calls: [],
      next_offset: null,
      promises: [],
      next_steps: [],
      buyer_intent_history: [],
    };

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => mockDetail,
    } as Response);

    const result = await fetchProspectDetail({
      prospectId: "11111111-1111-4111-8111-111111111111",
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      `${PROSPECTS_API}/11111111-1111-4111-8111-111111111111`,
      expect.anything(),
    );
    expect(result.prospect.name).toBe("Test Person");
    fetchSpy.mockRestore();
  });

  it("rejects non-UUID prospect id before fetching", async () => {
    await expect(
      fetchProspectDetail({ prospectId: "not-a-uuid" }),
    ).rejects.toThrow("Invalid prospect identifier.");
  });
});
