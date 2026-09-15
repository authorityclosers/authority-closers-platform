// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminReviewDetails } from "./admin-review-details";

const ids = {
  assignment: "11111111-1111-4111-8111-111111111111",
  tenant: "22222222-2222-4222-8222-222222222222",
  run: "33333333-3333-4333-8333-333333333333",
  reviewer: "44444444-4444-4444-8444-444444444444",
  recording: "66666666-6666-4666-8666-666666666666",
  permission: "77777777-7777-4777-8777-777777777777",
  checkpoint: "88888888-8888-4888-8888-888888888888",
  feedback: "99999999-9999-4999-8999-999999999999",
};
const digest = "a".repeat(64);

const assignment = {
  schema: "ac.sales-xray.review-assignment/1",
  id: ids.assignment,
  tenant_id: ids.tenant,
  run_id: ids.run,
  run_generation: 2,
  recipe_revision: "recipe-v1",
  source: {
    tenant_id: ids.tenant,
    recording_id: ids.recording,
    source_sha256: digest,
    source_revision: 1,
    permission_id: ids.permission,
    provenance_ref: `ref:conversation-permission:${ids.permission}`,
  },
  checkpoint: {
    id: ids.checkpoint,
    tenant_id: ids.tenant,
    recording_id: ids.recording,
    source_sha256: digest,
    source_revision: 1,
    stage: "C2",
    revision: "checkpoint-v1",
    cache_key: digest,
    manifest_sha256: digest,
    payload_sha256: digest,
  },
  reviewer_person_id: ids.reviewer,
  allowed_lenses: ["sales"],
  state: "submitted",
  created_at_epoch: 1_800_000_000,
  expires_at_epoch: 1_800_086_400,
  created_by_person_id: ids.reviewer,
};

function details(payload: unknown) {
  return {
    assignment,
    lifecycle: {
      state: "submitted",
      created_at_epoch: 1_800_000_000,
      expires_at_epoch: 1_800_086_400,
      revocation: null,
    },
    source: {
      tenant_id: ids.tenant,
      recording_id: ids.recording,
      source_sha256: digest,
      source_revision: 1,
      state: "ready",
      content_state: "retained",
      permission_expires_at_epoch: 1_800_086_400,
      retention_until_epoch: 1_800_086_400,
      permission_revoked_at_epoch: null,
    },
    review: {
      run_id: ids.run,
      run_generation: 2,
      recipe_revision: "recipe-v1",
      run_state: "completed",
      report_id: ids.run,
      report_state: "retained",
      checkpoint_id: ids.checkpoint,
      checkpoint_state: "retained",
    },
    feedback: [
      {
        id: ids.feedback,
        assignment_id: ids.assignment,
        tenant_id: ids.tenant,
        request_sha256: digest,
        payload_sha256: digest,
        created_at_epoch: 1_800_000_001,
        erased_at_epoch: null,
        state: "available",
        payload,
      },
    ],
    feedback_count: 1,
    available_feedback_count: 1,
    feedback_truncated: false,
  };
}

const feedback = {
  schema: "ac.sales-xray.review-feedback/1",
  id: ids.feedback,
  assignment_id: ids.assignment,
  tenant_id: ids.tenant,
  run_id: ids.run,
  reviewer_person_id: ids.reviewer,
  author_person_id: ids.reviewer,
  lens: "sales",
  lane: "sales",
  idempotency_key: "feedback-1",
  request_sha256: digest,
  evidence_refs: [{ checkpoint_id: ids.checkpoint, span_id: "segment-1" }],
  confidence: "high",
  feedback: "The opening established the buyer context.",
  proposed_correction: null,
  created_at_epoch: 1_800_000_001,
};

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(details(feedback))),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
}

describe("mounted Admin review detail", () => {
  it("renders saved feedback and lifecycle metadata from the Admin detail route", async () => {
    await act(async () =>
      root.render(<AdminReviewDetails assignmentId={ids.assignment} />),
    );
    await settle();

    expect(container.textContent).toContain("Saved review feedback");
    expect(container.textContent).toContain(
      "The opening established the buyer context.",
    );
    expect(container.textContent).toContain("Retention until");
    expect(container.textContent).toContain("submitted");
    expect(container.textContent).not.toContain("Open in Academy");
    expect(fetch).toHaveBeenCalledWith(
      `/v1/admin/conversation/review-assignments/${ids.assignment}`,
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("redacts an erased feedback payload while retaining its status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({
          ...details(null),
          feedback: [
            {
              ...details(null).feedback[0],
              state: "erased",
              erased_at_epoch: 1_800_000_002,
            },
          ],
          available_feedback_count: 0,
        }),
      ),
    );
    await act(async () =>
      root.render(<AdminReviewDetails assignmentId={ids.assignment} />),
    );
    await settle();

    expect(container.textContent).toContain("Erased");
    expect(container.textContent).toContain("feedback payload was erased");
    expect(container.textContent).not.toContain("The opening established");
  });

  it("ignores a late response for a previous assignment", async () => {
    let resolveA!: (response: Response) => void;
    let resolveB!: (response: Response) => void;
    const pendingA = new Promise<Response>((resolve) => {
      resolveA = resolve;
    });
    const pendingB = new Promise<Response>((resolve) => {
      resolveB = resolve;
    });
    const fetcher = vi.fn<typeof fetch>((input) =>
      String(input).endsWith(ids.assignment) ? pendingA : pendingB,
    );
    vi.stubGlobal("fetch", fetcher);

    await act(async () =>
      root.render(<AdminReviewDetails assignmentId={ids.assignment} />),
    );
    await act(async () =>
      root.render(<AdminReviewDetails assignmentId={ids.run} />),
    );
    resolveB(
      jsonResponse({
        ...details({
          ...feedback,
          feedback: "The newer assignment is current.",
        }),
        assignment: { ...assignment, id: ids.run },
        feedback: [
          {
            ...details(feedback).feedback[0],
            assignment_id: ids.run,
            payload: {
              ...feedback,
              assignment_id: ids.run,
              feedback: "The newer assignment is current.",
            },
          },
        ],
      }),
    );
    await settle();
    resolveA(jsonResponse(details(feedback)));
    await settle();

    expect(container.textContent).toContain("The newer assignment is current.");
    expect(container.textContent).not.toContain("The opening established");
  });

  it("clears old feedback after an Admin authorization denial on refresh", async () => {
    await act(async () =>
      root.render(<AdminReviewDetails assignmentId={ids.assignment} />),
    );
    await settle();
    expect(container.textContent).toContain("The opening established");

    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          jsonResponse({ detail: "The admin surface is required." }, 403),
        ),
    );
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>(
          "[aria-label='Refresh saved review feedback']",
        )!
        .click();
    });
    await settle();

    expect(container.textContent).toContain("The admin surface is required.");
    expect(container.textContent).not.toContain("The opening established");
  });
});
