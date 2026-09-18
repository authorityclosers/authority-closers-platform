import { describe, expect, it, vi } from "vitest";
import { createReviewAssignmentApi } from "./review-assignment-api";
import {
  assignmentResponse,
  ids,
  submissionResponse,
} from "./review-assignment-fixture";

describe("review assignment API adapter", () => {
  it("rejects missing or unsupported assignment schema versions", async () => {
    for (const schema of [undefined, "ac.sales-xray.review-assignment/2"]) {
      const payload = assignmentResponse();
      const fetcher = vi.fn().mockResolvedValue(
        Response.json({
          ...payload,
          assignment: { ...payload.assignment, schema },
        }),
      );
      await expect(
        createReviewAssignmentApi(fetcher).get(ids.assignment),
      ).rejects.toThrow("incomplete assignment");
    }
  });

  it("rejects unsupported feedback schema versions in saved history", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json(assignmentResponse()))
      .mockResolvedValueOnce(
        Response.json({
          items: [
            submissionResponse({ schema: "ac.sales-xray.review-feedback/2" }),
          ],
        }),
      );
    const api = createReviewAssignmentApi(fetcher);
    const loaded = await api.get(ids.assignment);
    await expect(api.history(loaded)).rejects.toThrow("invalid saved review");
  });

  it("accepts the actual DTO without a reviewer display object and saves only allowed fields", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json(assignmentResponse()))
      .mockResolvedValueOnce(
        Response.json(submissionResponse(), { status: 201 }),
      )
      .mockResolvedValueOnce(Response.json({ items: [submissionResponse()] }));
    const api = createReviewAssignmentApi(fetcher);
    const loaded = await api.get(ids.assignment);
    expect(loaded.assignment.reviewer.person_id).toBe(ids.reviewer);
    expect(loaded.assignment.report.title).toBe(
      "Synthetic conversation review",
    );
    const saved = await api.submit(
      loaded,
      {
        assignment_id: ids.assignment,
        recording_id: ids.recording,
        run_revision: "run",
        reviewer_id: ids.reviewer,
        lens: "sales",
        clip: loaded.assignment.clips[0]!,
        feedback: "The next step is grounded in the cited span.",
        confidence: "high",
      },
      "review-key-1",
    );
    expect(saved.id).toBe(ids.submission);
    const [, init] = fetcher.mock.calls[1]!;
    expect(JSON.parse(String(init?.body))).toEqual({
      schema: "ac.sales-xray.review-feedback/1",
      idempotency_key: "review-key-1",
      lens: "sales",
      evidence_refs: [{ checkpoint_id: ids.checkpoint, span_id: "segment-1" }],
      confidence: "high",
      feedback: "The next step is grounded in the cited span.",
    });
    expect(init).toMatchObject({
      cache: "no-store",
      credentials: "include",
      mode: "same-origin",
      redirect: "error",
    });
    expect((await api.history(loaded))[0]?.id).toBe(saved.id);
  });

  it.each([
    "https://evil.invalid/audio",
    "//evil.invalid/audio",
    "/v1/private-other/source",
    `/v1/conversation/review-assignments/${ids.assignment}/source?token=x`,
  ])("rejects unrelated playback path %s", async (audio) => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        Response.json({ ...assignmentResponse(), audio_source_url: audio }),
      );
    await expect(
      createReviewAssignmentApi(fetcher).get(ids.assignment),
    ).rejects.toThrow("audio source URL");
  });

  it("rejects wrong source/checkpoint bindings and invalid spans", async () => {
    const response = assignmentResponse();
    response.evidence_spans[0]!.checkpoint_id = ids.run;
    const fetcher = vi.fn().mockResolvedValue(Response.json(response));
    await expect(
      createReviewAssignmentApi(fetcher).get(ids.assignment),
    ).rejects.toThrow("assigned source");
  });

  it("does not claim success for a receipt with another author or body", async () => {
    for (const change of [
      { author_person_id: ids.run },
      { feedback: "Different feedback" },
    ]) {
      const fetcher = vi
        .fn()
        .mockResolvedValueOnce(Response.json(assignmentResponse()))
        .mockResolvedValueOnce(Response.json(submissionResponse(change)));
      const api = createReviewAssignmentApi(fetcher);
      const loaded = await api.get(ids.assignment);
      await expect(
        api.submit(
          loaded,
          {
            assignment_id: ids.assignment,
            recording_id: ids.recording,
            run_revision: "run",
            reviewer_id: ids.reviewer,
            lens: "sales",
            clip: loaded.assignment.clips[0]!,
            feedback: "The next step is grounded in the cited span.",
            confidence: "high",
          },
          "review-key-1",
        ),
      ).rejects.toThrow();
    }
  });
});
