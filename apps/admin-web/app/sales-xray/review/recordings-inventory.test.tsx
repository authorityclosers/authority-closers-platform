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
  latest_run: null,
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
    expect(container.textContent).not.toContain("Ready for review");
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
