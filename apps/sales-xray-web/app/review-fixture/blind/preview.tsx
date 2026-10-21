"use client";

/**
 * The blind Brain 4.0 rating with a fictional call, for screenshots on GitHub
 * (wb-ci --visual). Saves are answered here; nothing leaves the browser.
 */

import { useEffect, useState } from "react";

import { BlindFlow } from "../../review/blind-flow";
import type { SavedRow, Workspace } from "../../review/review-client";

const NAMES: [string, string, string][] = [
  ["D01", "Starting the Call", "How You Talk"],
  ["D02", "Setting the Plan", "How You Talk"],
  ["D03", "Tone, Pace & Pauses", "How You Talk"],
  ["D04", "Listening Well", "How You Talk"],
  ["D05", "Asking the Right Questions", "How You Talk"],
  ["D06", "Building Connection", "How You Talk"],
  ["D07", "Being Professional", "How You Talk"],
  ["D08", "Finding the Decision-Makers", "How Well You Understand the Buyer"],
  [
    "D09",
    "Understanding Problems & Goals",
    "How Well You Understand the Buyer",
  ],
  [
    "D10",
    "Understanding What They're Doing Now",
    "How Well You Understand the Buyer",
  ],
  ["D11", "Understanding the Real Impact", "How Well You Understand the Buyer"],
  [
    "D12",
    "Understanding How They Will Decide",
    "How Well You Understand the Buyer",
  ],
  ["D13", "Matching the Right Solution", "How Well You Move the Sale Forward"],
  [
    "D14",
    "Explaining the Solution Clearly",
    "How Well You Move the Sale Forward",
  ],
  ["D15", "Talking About Price & Budget", "How Well You Move the Sale Forward"],
  ["D16", "Handling Objections", "How Well You Move the Sale Forward"],
  ["D17", "Asking for the Decision", "How Well You Move the Sale Forward"],
  ["D18", "Setting Clear Next Steps", "How Well You Move the Sale Forward"],
];

const MINE = [4, 3, 3, 4, 3, 4, 4, 0, 3, 3, 2, 0, 3, 4, 2, 2, 3, 4];
const THEIRS = [4, 4, 0, 4, 4, 4, 4, 3, 4, 3, 3, 0, 4, 4, 4, 3, 3, 4];

const SEGMENTS = [
  ["s1", "a", 0, "Hi, thanks for taking the time today."],
  ["s2", "b", 6_000, "Sure. We get leads but most never reply."],
  ["s3", "a", 14_000, "What happens to a lead after it comes in?"],
  [
    "s4",
    "b",
    21_000,
    "Someone calls them back the next day, if they remember.",
  ],
  ["s5", "a", 61_000, "Our plan is fifty thousand a month."],
  ["s6", "b", 66_000, "That's more than we spend now."],
  ["s7", "a", 74_000, "Shall we talk again on Friday at four?"],
].map(([id, speaker_id, start_ms, text]) => ({
  id: String(id),
  speaker_id: String(speaker_id),
  start_ms: Number(start_ms),
  end_ms: Number(start_ms) + 5_000,
  text: String(text),
}));

function row(target: string, value: SavedRow["value"], n: number): SavedRow {
  return {
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    target,
    value,
    supersedes_id: null,
    created_at: "2026-10-21T08:00:00Z",
  };
}

function workspace(phase: "intro" | "rate" | "reveal"): Workspace {
  const rated = phase === "reveal" ? 18 : phase === "rate" ? 3 : 0;
  const saved: SavedRow[] = NAMES.slice(0, rated).map(([id], i) =>
    row(
      `brain4:${id}`,
      MINE[i]
        ? { rating: MINE[i], blind: true }
        : { skip: "not_applicable", blind: true },
      i + 1,
    ),
  );
  if (phase !== "intro")
    saved.push(
      row(
        "moment:01",
        {
          opinion: "Gave the price before asking what a lost lead costs them.",
          moment: { at_ms: 61_000, kind: "criticism", dimension: "D15" },
          blind: true,
        },
        40,
      ),
    );
  return {
    mode: "brain4_blind",
    review_id: "00000000-0000-4000-8000-000000000099",
    review_status: "blind_brain4_rating",
    lines: [],
    dimensions: NAMES.map(([id, label, category], i) => ({
      id,
      number: i + 1,
      label,
      category: category.toLowerCase().replaceAll(" ", "_"),
      category_label: category,
      about: `Fictional guide text: what to look for in ${label.toLowerCase()}.`,
      scale:
        "5 helped the call. 4 worked; nothing went wrong. 3 average. 2 hurt the call. 1 clearly damaging.",
    })),
    revealed: phase === "reveal",
    brain4:
      phase === "reveal"
        ? {
            status: "read",
            label: "beta",
            dimensions: NAMES.map(([id], i) => ({
              id,
              rating: THEIRS[i] || null,
              observed: THEIRS[i]
                ? "Fictional: you asked how leads are handled today."
                : "Not enough in the call to judge.",
              coaching: THEIRS[i]
                ? "On your next relevant call, ask what a lost lead costs before the price."
                : null,
              evidence: THEIRS[i]
                ? [
                    {
                      segment_id: "s3",
                      quote: SEGMENTS[2].text,
                      start_ms: 14_000,
                    },
                  ]
                : [],
            })),
          }
        : null,
    saved,
    audio_source_url: "/fictional-audio.mp3",
    transcript: { segments: SEGMENTS },
    context: {
      recorded_at: "2026-10-21T10:30:00Z",
      duration_ms: 840_000,
      summary: null,
      verdict: null,
    },
  };
}

export function BlindPreview({
  phase,
}: {
  phase: "intro" | "rate" | "reveal";
}) {
  const [data, setData] = useState(() => workspace(phase));
  useEffect(() => {
    const real = window.fetch.bind(window);
    let n = 100;
    window.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.startsWith("/v1/sales-xray/review/") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        const value: Record<string, unknown> = { ...body };
        for (const key of ["review_id", "target", "supersedes_id"])
          delete value[key];
        n += 1;
        return new Response(
          JSON.stringify(
            row(String(body.target), value as SavedRow["value"], n),
          ),
          { status: 201, headers: { "content-type": "application/json" } },
        );
      }
      return real(input, init);
    };
    return () => {
      window.fetch = real;
    };
  }, []);
  return (
    <div style={{ height: "100dvh" }}>
      <BlindFlow
        assignmentId="00000000-0000-4000-8000-000000000001"
        workspace={data}
        onFinished={() => setData(workspace("intro"))}
        onReload={() => setData(workspace("reveal"))}
      />
    </div>
  );
}
