// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, expect, it, vi } from "vitest";

import { RecordingsInventory } from "./recordings-inventory";
import { loadAdminRecordings } from "./recordings-api";

vi.mock("./recordings-api", () => ({
  loadAdminRecordings: vi.fn(),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const recording = {
  id: "11111111-1111-4111-8111-111111111111",
  owner: {
    kind: "learner" as const,
    label: "Alex Seller",
    person_id: "22222222-2222-4222-8222-222222222222",
    display_name: "Alex Seller",
    email: "alex@example.com",
    claimed: true,
  },
  uploaded_at: "2026-09-14T12:30:00+00:00",
  recording_state: "ready" as const,
  source: {
    bytes: 1024,
    content_type: "audio/ogg",
    sha256: "a".repeat(64),
    revision: 1,
  },
  duration: {
    milliseconds: 12345,
    seconds: 12.345,
    source: "native_measurement" as const,
  },
  status: "held" as const,
  latest_run: {
    id: "33333333-3333-4333-8333-333333333333",
    state: "completed" as const,
    generation: 1,
    recipe_revision: "audioatlas-16000-v1",
    created_at: "2026-09-14T12:31:00+00:00",
    completed_at: "2026-09-14T12:32:00+00:00",
    provider_stages: [
      {
        stage: "C4" as const,
        run_id: "33333333-3333-4333-8333-333333333333",
        state: "completed" as const,
        provider: "gemini",
        model: "gemini-3.8-flash",
        request_id: "request-1",
        usage: { total_tokens: 120 },
        receipt_state: "recorded" as const,
        cost_state: "reconciliation_required" as const,
        usage_estimate_paise: 2,
        usage_estimate_state: "available" as const,
        usage_estimate_basis:
          "provider_input_and_output_tokens_x_approved_token_rates",
        pricing_snapshot: {
          schema: "ac.sales-xray.pricing-snapshot/1" as const,
          evidence_release_sha: "0847db5d3ca1ed825b68c226713d0f52d11683b1",
          provider: "gemini",
          model: "gemini-3.8-flash",
          currency: "INR" as const,
          usd_to_inr: 100,
          source_date: "2026-09-14",
          pricing_ref: "ref:pricing/gemini-38-intro-20260914",
          evidence_sha256: "b".repeat(64),
          source_url: "https://ai.google.dev/gemini-api/docs/latest-model",
          rate_basis: "per_million_tokens" as const,
          usd_per_hour: null,
          input_usd_per_million_tokens: 0.75,
          output_usd_per_million_tokens: 3.75,
          is_billing_rate: false as const,
        },
      },
    ],
  },
  processing_plan: {
    id: "33333333-3333-4333-8333-333333333333",
    state: "held" as const,
  },
  report: {
    available: true,
    id: "33333333-3333-4333-8333-333333333333",
    run_id: "33333333-3333-4333-8333-333333333333",
    review_eligible: false,
    invite_eligible: false,
  },
  cost: {
    currency: "INR" as const,
    scope: "recording_total" as const,
    reservation_paise: 100,
    estimate_paise: 100,
    actual_paise: null,
    reservation_state: "reserved" as const,
    actual_state: "not_settled" as const,
    usage_estimate_paise: 2,
    usage_estimate_state: "available" as const,
    usage_estimate_basis: "provider_usage_x_approved_planning_rates",
    usage_estimate_currency: "INR" as const,
    usage_estimate_fx_usd_to_inr: 100,
    usage_estimate_source_date: "2026-09-14",
    usage_estimate_is_billing_rate: false as const,
  },
};

beforeEach(() => {
  vi.mocked(loadAdminRecordings).mockReset();
  vi.mocked(loadAdminRecordings).mockResolvedValue({
    items: [recording],
    next_cursor: null,
  });
});

it("does not label an available report ready while review eligibility is blocked", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => {
      root.render(<RecordingsInventory onSelectRun={vi.fn()} />);
    });
    await vi.waitFor(() => expect(loadAdminRecordings).toHaveBeenCalled());
    await vi.waitFor(() =>
      expect(container.textContent).toContain("Not ready"),
    );
    expect(container.textContent).toContain("Not ready");
    expect(container.textContent).toContain("gemini / gemini-3.8-flash");
    expect(container.textContent).toContain("120 tokens");
    expect(container.textContent).toContain("charge pending reconciliation");
    expect(container.textContent).toContain(
      "₹0.02 · planning @ ₹100/USD · source 2026-09-14",
    );
    expect(container.textContent).not.toContain("Ready for review");
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

it("shows a saved upload with completed audio checks as report pending", async () => {
  vi.mocked(loadAdminRecordings).mockResolvedValue({
    items: [
      {
        ...recording,
        status: "completed",
        latest_run: { ...recording.latest_run, provider_stages: [] },
        processing_plan: null,
        report: {
          available: false,
          id: null,
          run_id: null,
          review_eligible: false,
          invite_eligible: false,
        },
      },
    ],
    next_cursor: null,
  });
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const onSelectRun = vi.fn();
  try {
    await act(async () => {
      root.render(<RecordingsInventory onSelectRun={onSelectRun} />);
    });
    await vi.waitFor(() =>
      expect(container.textContent).toContain("Report pending"),
    );
    expect(container.textContent).toContain("Audio checks complete");
    expect(container.textContent).not.toContain("Ready for review");
    expect(container.textContent).not.toContain("Use for review / invite");
    expect(onSelectRun).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
