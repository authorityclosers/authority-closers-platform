import { describe, expect, it, vi } from "vitest";

import { loadAdminRecordings } from "./recordings-api";

const ids = {
  recording: "11111111-1111-4111-8111-111111111111",
  person: "22222222-2222-4222-8222-222222222222",
  run: "33333333-3333-4333-8333-333333333333",
};

const payload = {
  items: [
    {
      id: ids.recording,
      owner: {
        kind: "learner",
        label: "Alex Seller",
        person_id: ids.person,
        display_name: "Alex Seller",
        email: "alex@example.com",
        claimed: true,
      },
      uploaded_at: "2026-09-14T12:30:00+00:00",
      recording_state: "ready",
      source: {
        bytes: 1024,
        content_type: "audio/ogg",
        sha256: "a".repeat(64),
        revision: 1,
      },
      duration: {
        milliseconds: 12345,
        seconds: 12.345,
        source: "native_measurement",
      },
      status: "completed",
      latest_run: {
        id: ids.run,
        state: "completed",
        generation: 1,
        recipe_revision: "audioatlas-16000-v1",
        created_at: "2026-09-14T12:31:00+00:00",
        completed_at: "2026-09-14T12:32:00+00:00",
        provider_stages: [
          {
            stage: "C4",
            run_id: ids.run,
            state: "completed",
            provider: "gemini",
            model: "gemini-3.8-flash",
            request_id: "req-1",
            usage: { promptTokenCount: 100, candidatesTokenCount: 20 },
            receipt_state: "recorded",
            cost_state: "reconciliation_required",
          },
        ],
      },
      processing_plan: null,
      report: {
        available: true,
        id: ids.run,
        run_id: ids.run,
        review_eligible: true,
        invite_eligible: true,
      },
      cost: {
        currency: "INR",
        scope: "current_plan",
        reservation_paise: null,
        estimate_paise: 500,
        actual_paise: null,
        reservation_state: null,
        actual_state: "not_settled",
        usage_estimate_paise: null,
        usage_estimate_state: "rate_unavailable",
      },
    },
  ],
  next_cursor: "next-page",
};

describe("admin recordings API", () => {
  it("requests bounded search and cursor values and validates the receipt", async () => {
    const fetcher = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    const result = await loadAdminRecordings({
      limit: 25,
      cursor: "cursor-1",
      search: "Alex Seller",
      fetcher,
    });

    expect(result.items[0]?.cost.actual_paise).toBeNull();
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/admin/conversation/recordings?limit=25&cursor=cursor-1&q=Alex+Seller",
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("rejects an unbounded page size before making a request", async () => {
    const fetcher = vi.fn<typeof fetch>();
    await expect(loadAdminRecordings({ limit: 51, fetcher })).rejects.toThrow(
      "between 1 and 50",
    );
    expect(fetcher).not.toHaveBeenCalled();
  });
});
