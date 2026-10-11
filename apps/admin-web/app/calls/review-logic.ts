/** Pure logic behind the review screen: waveform bars, keys, run comparison. */
import type { Bundle, Report, Waveform } from "./call-data";
import { REPORT_SKILLS, skillState } from "./report-pillars";

/** `count` bars from the RMS envelope: the loudest point in each slice, 0..1. */
export function waveformBars(
  waveform: Waveform | null,
  count: number,
): number[] {
  if (!waveform || waveform.points.length === 0 || count <= 0) return [];
  const levels = waveform.points.map((point) => point.level ?? 0);
  const peak = Math.max(...levels, 0);
  if (peak <= 0) return Array.from({ length: count }, () => 0);
  const bars: number[] = [];
  for (let bar = 0; bar < count; bar++) {
    const from = Math.floor((bar / count) * levels.length);
    const to = Math.max(
      from + 1,
      Math.floor(((bar + 1) / count) * levels.length),
    );
    let loudest = 0;
    for (let index = from; index < to && index < levels.length; index++)
      loudest = Math.max(loudest, levels[index] ?? 0);
    bars.push(Math.min(1, loudest / peak));
  }
  return bars;
}

export type ReviewTab =
  | "report"
  | "pillars"
  | "coaching"
  | "metrics"
  | "runs"
  | "transcript";
export type ReviewAction =
  | { kind: "toggle" }
  | { kind: "seek"; byMs: number }
  | { kind: "speed"; step: 1 | -1 }
  | { kind: "tab"; tab: ReviewTab }
  | { kind: "call"; step: 1 | -1 }
  | { kind: "help" }
  | { kind: "link" }
  | { kind: "close" };

/** The review screen's keys. Single keys only act outside text fields (the caller checks). */
export function keyAction(event: {
  key: string;
  shiftKey?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
}): ReviewAction | null {
  if (event.metaKey || event.ctrlKey || event.altKey) return null;
  const big = event.shiftKey ? 15_000 : 5_000;
  switch (event.key) {
    case " ":
    case "k":
      return { kind: "toggle" };
    case "ArrowLeft":
    case "j":
      return { kind: "seek", byMs: -big };
    case "ArrowRight":
    case "l":
      return { kind: "seek", byMs: big };
    case ".":
    case ">":
      return { kind: "speed", step: 1 };
    case ",":
    case "<":
      return { kind: "speed", step: -1 };
    case "r":
      return { kind: "tab", tab: "report" };
    case "s":
      return { kind: "tab", tab: "pillars" };
    case "c":
      return { kind: "tab", tab: "coaching" };
    case "m":
      return { kind: "tab", tab: "metrics" };
    case "u":
      return { kind: "tab", tab: "runs" };
    case "t":
      return { kind: "tab", tab: "transcript" };
    case "n":
      return { kind: "call", step: 1 };
    case "p":
      return { kind: "call", step: -1 };
    case "y":
      return { kind: "link" };
    case "?":
      return { kind: "help" };
    case "Escape":
      return { kind: "close" };
    default:
      return null;
  }
}

/** A shared link's moment (?at=, in ms): a whole number within a day, else none. */
export function startAt(value: string | undefined): number | null {
  if (!value || !/^\d{1,8}$/.test(value)) return null;
  const ms = Number(value);
  return ms < 86_400_000 ? ms : null;
}

export const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2] as const;
export function nextSpeed(current: number, step: 1 | -1): number {
  const index = SPEEDS.findIndex((speed) => speed >= current);
  const at = index < 0 ? SPEEDS.length - 1 : index;
  return SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, at + step))]!;
}

export const SHORTCUTS: readonly [string, string][] = [
  ["Space / K", "Play or pause"],
  ["← / J · → / L", "Back or forward 5 s (Shift: 15 s)"],
  [", / .", "Slower or faster"],
  ["R · S · C · M · U", "Report · Six pillars · Coaching · Metrics · Runs"],
  ["T", "Transcript (phones)"],
  ["N / P", "Next or previous call in the queue"],
  ["Y", "Copy a link to this moment of the call"],
  ["?", "Show or hide these keys"],
];

/* ---------- Compare two runs ---------- */

export type CompareRow = {
  label: string;
  left: string;
  right: string;
  same: boolean;
};

const titles = (items: { title: string }[]) =>
  items.map((item) => item.title).join(" · ") || "None";

/** Field-by-field differences between two runs' reports, in reading order. */
export function compareReports(left: Report, right: Report): CompareRow[] {
  const row = (label: string, a: string, b: string): CompareRow => ({
    label,
    left: a,
    right: b,
    same: a.trim() === b.trim(),
  });
  const rows: CompareRow[] = [
    row("Summary", left.summary, right.summary),
    row("Verdict", left.verdict, right.verdict),
    row("Strengths", titles(left.strengths), titles(right.strengths)),
    row("What didn't", titles(left.improvements), titles(right.improvements)),
    row(
      "Missed opportunities",
      titles(left.missedOpportunities),
      titles(right.missedOpportunities),
    ),
    row(
      "Objections",
      titles(left.objectionAnalysis),
      titles(right.objectionAnalysis),
    ),
    row("Closing", titles(left.closingAnalysis), titles(right.closingAnalysis)),
  ];
  for (const [id, label] of REPORT_SKILLS) {
    const a = left.dimensions.find((item) => item.id === id);
    const b = right.dimensions.find((item) => item.id === id);
    rows.push(
      row(
        label,
        a ? (skillState(a) ?? "Not established") : "Not assessed",
        b ? (skillState(b) ?? "Not established") : "Not assessed",
      ),
    );
  }
  const focus = (report: Report) =>
    report.overview?.nextCallFocus?.behavior ??
    report.overview?.finalAssessment?.fixFirst ??
    "None";
  rows.push(row("Coaching focus", focus(left), focus(right)));
  return rows;
}

/** Call length in ms: the waveform's, else the transcript's last word. */
export function durationOf(bundle: Bundle): number | null {
  if (bundle.waveform?.durationMs) return bundle.waveform.durationMs;
  const last = bundle.transcript.segments.at(-1);
  return last ? last.endMs : null;
}
