import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { goldWorkspace, type GoldWorkspace } from "./gold-review-api";
import { GoldReviewWorkspace } from "./gold-review-workspace";

export function fictionalWorkspace(): GoldWorkspace {
  const id = "10000000-0000-4000-8000-000000000001";
  return {
    review_id: id,
    version: "pointer-review/1",
    review_status: "ai_draft_not_dipak_reviewed",
    ai_sha256: "a".repeat(64),
    call: {
      recording_id: id,
      run_id: id,
      source_sha256: "b".repeat(64),
      transcript_revision: "fictional/1",
    },
    lines: [
      ...Array.from({ length: 27 }, (_, i) => ({
        target: `pointer-${i + 1}`,
        label: `${i + 1}. ${["Opening the call", "Purpose and agenda", "Tone and confidence", "Listening", "Open questions"][i % 5]}`,
        ai: {
          status: "good",
          score: 72,
          what_happened:
            "You asked what the buyer wants to change, then checked the timing.",
          evidence: [{ quote: "We need the team ready before next month." }],
          how_to_improve: ["Ask who signs off on the decision."],
        },
      })),
      {
        target: "final_call_outcome",
        label: "Final Call Outcome",
        ai: {
          notes: ["The buyer will check with their partner."],
          next_steps: [{ text: "Call back on Tuesday." }],
        },
      },
      {
        target: "coaching",
        label: "Coaching",
        ai: [
          { pointer: "Listening", tips: ["Pause after asking a question."] },
        ],
      },
    ],
    saved: [],
    history_count: 0,
    audio_source_url: `/v1/reviewer/review-assignments/${id}/source`,
    transcript: {
      segments: [
        {
          id: "s1",
          speaker_id: "Buyer",
          text: "We need the team ready before next month.",
          start_ms: 12000,
        },
      ],
    },
  };
}

describe("Gold reviewer report", () => {
  it("shows all 29 saved AI lines and independent judgement controls", () => {
    const data = fictionalWorkspace();
    const html = renderToStaticMarkup(
      <GoldReviewWorkspace assignmentId={data.review_id} initial={data} />,
    );
    expect(html.match(/<textarea/g)).toHaveLength(29);
    expect(html.match(/Save this line/g)).toHaveLength(29);
    expect(html).toContain("AI draft · not reviewed by Dipak");
    expect(html).toContain("Final Call Outcome");
    expect(html).toContain("Coaching");
    expect(html).toContain("72/100");
    expect(html).toContain("0 of 29 lines reviewed");
    expect(html).toContain("Read the call transcript");
  });
  it("refuses partial AI responses before displaying a review", () => {
    const data = fictionalWorkspace();
    expect(goldWorkspace.safeParse(data).success).toBe(true);
    expect(
      goldWorkspace.safeParse({ ...data, lines: data.lines.slice(0, 3) })
        .success,
    ).toBe(false);
  });
});
