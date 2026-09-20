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
      submission_id: ids.person,
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
            usage_estimate_paise: 2,
            usage_estimate_state: "available",
            usage_estimate_basis:
              "provider_input_and_output_tokens_x_approved_token_rates",
            pricing_snapshot: {
              schema: "ac.sales-xray.pricing-snapshot/1",
              evidence_release_sha: "0847db5d3ca1ed825b68c226713d0f52d11683b1",
              provider: "gemini",
              model: "gemini-3.8-flash",
              currency: "INR",
              usd_to_inr: 100,
              source_date: "2026-09-14",
              pricing_ref: "ref:pricing/gemini-38-intro-20260914",
              evidence_sha256: "b".repeat(64),
              source_url: "https://ai.google.dev/gemini-api/docs/latest-model",
              rate_basis: "per_million_tokens",
              usd_per_hour: null,
              input_usd_per_million_tokens: 0.75,
              output_usd_per_million_tokens: 3.75,
              is_billing_rate: false,
            },
          },
        ],
      },
      runtime_trace: {
        submission_id: ids.person,
        binding_state: "verified",
        source_revision: 1,
        generation: 1,
        scope_complete: true,
        plans: [],
        tasks: [],
        publication: { validation_state: "not_checked" },
        future_worker_detail: { stage: "C6", retryable: true },
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
        usage_estimate_basis: null,
        usage_estimate_currency: null,
        usage_estimate_fx_usd_to_inr: null,
        usage_estimate_source_date: null,
        usage_estimate_is_billing_rate: null,
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
    expect(result.items[0]?.submission_id).toBe(ids.person);
    expect(result.items[0]?.runtime_trace?.future_worker_detail).toEqual({
      stage: "C6",
      retryable: true,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/admin/conversation/recordings?limit=25&cursor=cursor-1&q=Alex+Seller",
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("accepts a Deepgram per-minute planning snapshot without treating it as billing", async () => {
    const deepgramPayload = JSON.parse(JSON.stringify(payload)) as {
      items: Array<{
        latest_run: {
          provider_stages: Array<{
            provider: string | null;
            model: string | null;
            usage: Record<string, number> | null;
            usage_estimate_paise: number | null;
            usage_estimate_basis: string | null;
            pricing_snapshot: Record<string, unknown> | null;
          }>;
        } | null;
      }>;
    };
    const stage = deepgramPayload.items[0]?.latest_run?.provider_stages[0];
    if (!stage || !stage.pricing_snapshot)
      throw new Error("fixture is incomplete");
    stage.provider = "deepgram";
    stage.model = "nova-3";
    stage.usage = null;
    stage.usage_estimate_paise = 23;
    stage.usage_estimate_basis =
      "native_duration_ms_x_approved_per_minute_rate";
    stage.pricing_snapshot = {
      ...stage.pricing_snapshot,
      evidence_release_sha: "724f3ab549e1837bc0f5ed49aa298d4fd0f308a1",
      provider: "deepgram",
      model: "nova-3",
      source_date: "2026-09-15",
      pricing_ref: "ref:pricing/deepgram-nova-3-multilingual-20260915",
      evidence_sha256:
        "e4ac299a8e030cd9b6e22d517293fb979bf9bd8797f4d67faee86a28e3ffd1a7",
      source_url: "https://deepgram.com/pricing",
      rate_basis: "per_minute",
      usd_per_hour: null,
      usd_per_minute: 0.0052,
      input_usd_per_million_tokens: null,
      output_usd_per_million_tokens: null,
    };

    const fetcher = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(deepgramPayload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    const result = await loadAdminRecordings({ fetcher });
    const pricing =
      result.items[0]?.latest_run?.provider_stages[0]?.pricing_snapshot;
    expect(pricing?.rate_basis).toBe("per_minute");
    expect(pricing?.usd_per_minute).toBe(0.0052);
    expect(
      result.items[0]?.latest_run?.provider_stages[0]?.usage_estimate_paise,
    ).toBe(23);
    expect(pricing?.is_billing_rate).toBe(false);
  });

  it("keeps pricing snapshots strict after adding the supported rate basis", async () => {
    const invalidPayload = JSON.parse(
      JSON.stringify(payload),
    ) as typeof payload;
    const snapshot =
      invalidPayload.items[0]?.latest_run?.provider_stages[0]?.pricing_snapshot;
    if (!snapshot) throw new Error("fixture is incomplete");
    (snapshot as typeof snapshot & { untrusted_rate: number }).untrusted_rate =
      1;

    const fetcher = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(invalidPayload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await expect(loadAdminRecordings({ fetcher })).rejects.toThrow();
  });

  it("rejects an unbounded page size before making a request", async () => {
    const fetcher = vi.fn<typeof fetch>();
    await expect(loadAdminRecordings({ limit: 51, fetcher })).rejects.toThrow(
      "between 1 and 50",
    );
    expect(fetcher).not.toHaveBeenCalled();
  });
});
