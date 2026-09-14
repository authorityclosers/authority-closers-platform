import { describe, expect, it, vi } from "vitest";

import { loadAdminReport } from "./admin-report-api";

const runId = "33333333-3333-4333-8333-333333333333";
const payload = {
  id: "44444444-4444-4444-8444-444444444444",
  run_id: runId,
  recording_id: "11111111-1111-4111-8111-111111111111",
  tenant_id: "206ccee8-a246-433b-b6d3-78eb21592a5c",
  source: {
    sha256: "a".repeat(64),
    revision: 1,
    retention_until: "2026-09-22T12:00:00+00:00",
  },
  report: {
    summary: "A bounded summary.",
    strengths: [],
    missed_opportunities: [],
    improvements: [],
    objection_analysis: [],
    closing_analysis: [],
    verdict: "Continue with evidence-backed practice.",
    review_status: "draft_not_dipak_adjudicated",
    source_label: "Private recording",
    source_sha256: "a".repeat(64),
    transcript_revision: "transcript-1",
    dimensions: [],
    report_sections: [],
  },
  message: "Private report loaded for authorized Admin review.",
};

describe("admin report API", () => {
  it("reads a validated report without query parameters", async () => {
    const fetcher = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    const result = await loadAdminReport({ runId, fetcher });

    expect(result.report.summary).toBe("A bounded summary.");
    expect(fetcher).toHaveBeenCalledWith(
      `/v1/admin/conversation/runs/${runId}/report`,
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("rejects a non-UUID before making a request", async () => {
    const fetcher = vi.fn<typeof fetch>();
    await expect(loadAdminReport({ runId: "run-1", fetcher })).rejects.toThrow(
      "canonical UUID",
    );
    expect(fetcher).not.toHaveBeenCalled();
  });
});
