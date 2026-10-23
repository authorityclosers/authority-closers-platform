"use client";

/**
 * The Report review with a fictional call, for screenshots on GitHub (wb-ci
 * --visual). Saves are answered here; nothing leaves the browser.
 */

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import type {
  ReportItem,
  ReportSection,
  SavedRow,
  Workspace,
} from "../../review/review-client";

type Phase = "start" | "fix" | "text" | "done";

// Browser only: the call's time is shown in the viewer's time zone, which the server
// rendering this fixture does not share (the real /review loads its call in the browser).
const ReportFlow = dynamic(
  () => import("../../review/report-flow").then((module) => module.ReportFlow),
  { ssr: false },
);

const SKILLS = [
  "Starting the Call",
  "Setting the Plan",
  "Tone, Pace & Pauses",
  "Listening Well",
  "Asking the Right Questions",
  "Building Connection",
  "Being Professional",
  "Finding the Decision-Makers",
  "Understanding Problems & Goals",
  "Understanding What They're Doing Now",
  "Understanding the Real Impact",
  "Understanding How They Will Decide",
  "Matching the Right Solution",
  "Explaining the Solution Clearly",
  "Talking About Price & Budget",
  "Handling Objections",
  "Asking for the Decision",
  "Setting Clear Next Steps",
];
const RATINGS = [4, 4, 0, 4, 3, 4, 4, 3, 4, 3, 3, 0, 4, 4, 2, 3, 3, 4];

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

const quote = (n: number) => ({
  segment_id: SEGMENTS[n].id,
  quote: SEGMENTS[n].text,
  start_ms: SEGMENTS[n].start_ms,
});

function text(
  section: string,
  id: string,
  label: string,
  words: string,
  detail: string | null = null,
  evidence: ReportItem["evidence"] = [],
): ReportItem {
  return {
    id: `${section}.${id}`,
    section,
    label,
    kind: "text",
    rating: null,
    text: words,
    detail,
    evidence,
  };
}

const SECTIONS: ReportSection[] = [
  {
    id: "brain4",
    label: "AI coaching score",
    items: SKILLS.map((label, i) => ({
      id: `brain4.D${String(i + 1).padStart(2, "0")}`,
      section: "brain4",
      label,
      kind: "rating",
      number: i + 1,
      rating: RATINGS[i] || null,
      text: RATINGS[i]
        ? "Fictional: you asked how leads are handled today before talking about the plan."
        : "Not enough in the call to judge.",
      detail: RATINGS[i]
        ? "On your next relevant call, ask what a lost lead costs before you give the price."
        : null,
      evidence: RATINGS[i] ? [quote(2)] : [],
    })),
  },
  {
    id: "overview",
    label: "Overview",
    items: [
      text(
        "overview",
        "summary",
        "Summary",
        "Fictional: a first call about lead follow-up. The buyer felt the price was high.",
      ),
      text(
        "overview",
        "biggest_strength",
        "Biggest strength",
        "You asked what happens to a lead after it comes in.",
        null,
        [quote(2)],
      ),
      text(
        "overview",
        "biggest_improvement",
        "Biggest improvement",
        "Give the price after showing what lost leads cost them.",
        null,
        [quote(4)],
      ),
    ],
  },
  {
    id: "outcome",
    label: "Outcome",
    items: [
      text("outcome", "stages", "Stages", "Discovery · Negotiation"),
      text(
        "outcome",
        "suggested_action",
        "Suggested action",
        "Send the plan with the cost of a lost lead before Friday.",
      ),
    ],
  },
  {
    id: "outcome.next_steps",
    label: "Next steps",
    items: [
      text(
        "outcome.next_steps",
        "1",
        "Next step 1",
        "Call again with both partners.",
        "Friday 4 PM · you",
        [quote(6)],
      ),
    ],
  },
  {
    id: "buyer",
    label: "Buyer",
    items: [
      text(
        "buyer",
        "need",
        "Need",
        "Leads go cold before anyone calls back.",
        "Confirmed",
        [quote(3)],
      ),
      text(
        "buyer",
        "budget",
        "Budget",
        "More than they spend now.",
        "Unclear",
        [quote(5)],
      ),
    ],
  },
];

const ITEMS = SECTIONS.flatMap((s) => s.items);

function row(target: string, value: SavedRow["value"], n: number): SavedRow {
  return {
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    target,
    value,
    supersedes_id: null,
    created_at: "2026-10-23T08:00:00Z",
  };
}

function workspace(phase: Phase): Workspace {
  const upTo =
    phase === "done"
      ? ITEMS.length
      : phase === "text"
        ? ITEMS.findIndex((i) => i.id === "overview.biggest_improvement")
        : phase === "fix"
          ? 14
          : 0;
  const saved = ITEMS.slice(0, upTo).map((item, i) =>
    row(
      `item:${item.id}`,
      i === 2
        ? { skip: "audio_unclear" }
        : i % 7 === 6
          ? item.kind === "rating"
            ? { verdict: "fix", rating: 3, opinion: "Close, a 3." }
            : { verdict: "fix", correction: "Fictional fix." }
          : i % 9 === 8
            ? { verdict: "disagree", opinion: "Not what happened." }
            : { verdict: "agree" },
      i + 1,
    ),
  );
  return {
    mode: "report",
    review_id: "00000000-0000-4000-8000-000000000099",
    review_status: "report_review",
    lines: [],
    sections: SECTIONS,
    saved,
    audio_source_url: "/fictional-audio.mp3",
    transcript: { segments: SEGMENTS },
    context: {
      recorded_at: "2026-10-23T10:30:00Z",
      duration_ms: 840_000,
      summary: "Fictional: a first call about lead follow-up.",
      verdict: null,
    },
  };
}

export function ReportPreview({ phase }: { phase: Phase }) {
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
  // The Fix screens: once the flow has loaded, choose Fix (and a rating) as the
  // reviewer would.
  useEffect(() => {
    if (phase !== "fix" && phase !== "text") return;
    const button = (match: (text: string) => boolean) =>
      [...document.querySelectorAll("button")].find((b) =>
        match(b.textContent ?? ""),
      );
    let fixed = false;
    const timer = window.setInterval(() => {
      if (!fixed) {
        const fix = button((text) => text.startsWith("Fix"));
        if (!fix) return;
        fix.click();
        fixed = true;
        if (phase === "text") window.clearInterval(timer);
        return;
      }
      button((text) => text === "3")?.click();
      window.clearInterval(timer);
    }, 100);
    return () => window.clearInterval(timer);
  }, [phase]);
  return (
    <div style={{ height: "100dvh" }}>
      <ReportFlow
        assignmentId="00000000-0000-4000-8000-000000000001"
        workspace={data}
        onFinished={() => setData(workspace("start"))}
        onReload={() => setData(workspace(phase))}
      />
    </div>
  );
}
