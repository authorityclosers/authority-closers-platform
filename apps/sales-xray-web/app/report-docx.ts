/*
 * Report Document mode (AUT-983 redo, owner 5 Oct 2026): one compact,
 * evidence-first Word file built with docx.js. The app previews this exact
 * file and the download is the same bytes.
 *
 * Page 1 is the one-page review (outcome, numbers, who spoke when, keep / fix
 * first, the next call). Page 2 holds the evidence (moments, missed chances,
 * skills, practice, facts). Every time printed here is a recording time.
 */
import {
  AlignmentType,
  Bookmark,
  BorderStyle,
  Document,
  Footer,
  HeightRule,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableLayoutType,
  TableRow,
  TextRun,
  VerticalAlign,
  WidthType,
} from "docx";
import type { CallRecord } from "./call-record-contract";
import type {
  Finding,
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import type { DocumentReportData } from "./report-document-data";
import { buildPillarReportDocx } from "./report-pillar-docx";

export { DOCUMENT_CHAPTERS } from "./report-document-data";

export type ReportDocxInput = {
  title: string;
  callDate?: string | null;
  callType?: string | null;
  language?: string | null;
  durationMs?: number | null;
  report: SalesReport;
  transcript?: Transcript | null;
  callRecord?: CallRecord | null;
  /** Display name for a transcript speaker id (from the speaker map). */
  speakerName?: (speakerId: string) => string | null | undefined;
  people?: string[];
  generatedAt?: Date;
};

// A4 with 1.5 cm margins, in twips.
const PAGE = { width: 11906, height: 16838, margin: 850 };
const W = PAGE.width - 2 * PAGE.margin;

const C = {
  ink: "0F1B2D",
  body: "2B3645",
  muted: "667085",
  faint: "98A2B3",
  line: "DCE1E8",
  panel: "F4F6F9",
  white: "FFFFFF",
  teal: "0B7A70",
  tealBg: "E4F3F0",
  amber: "A15C07",
  amberBg: "FCF1DF",
  red: "B42318",
  redBg: "FBE8E6",
  blue: "1F4E99",
  blueBg: "E7EEF9",
  voiceA: "0B7A70",
  voiceB: "3B4A6B",
};

const FONT = {
  ascii: "Calibri",
  hAnsi: "Calibri",
  eastAsia: "Calibri",
  cs: "Nirmala UI",
};

type RunStyle = {
  size?: number;
  bold?: boolean;
  italics?: boolean;
  color?: string;
  caps?: boolean;
  spacing?: number;
};

function run(text: string, style: RunStyle = {}) {
  const size = style.size ?? 19;
  return new TextRun({
    text,
    font: FONT,
    size,
    sizeComplexScript: size,
    bold: style.bold,
    boldComplexScript: style.bold,
    italics: style.italics,
    italicsComplexScript: style.italics,
    color: style.color ?? C.body,
    allCaps: style.caps,
    characterSpacing: style.spacing,
  });
}

type ParaStyle = {
  after?: number;
  before?: number;
  line?: number;
  align?: (typeof AlignmentType)[keyof typeof AlignmentType];
  keepNext?: boolean;
  border?: string;
  pageBreakBefore?: boolean;
};

function para(children: (TextRun | Bookmark)[], style: ParaStyle = {}) {
  return new Paragraph({
    children,
    alignment: style.align,
    keepNext: style.keepNext,
    keepLines: true,
    pageBreakBefore: style.pageBreakBefore,
    spacing: {
      before: style.before ?? 0,
      after: style.after ?? 0,
      line: style.line ?? 252,
    },
    border: style.border
      ? {
          bottom: {
            style: BorderStyle.SINGLE,
            size: 6,
            color: style.border,
            space: 4,
          },
        }
      : undefined,
  });
}

const NONE = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const NO_BORDERS = {
  top: NONE,
  bottom: NONE,
  left: NONE,
  right: NONE,
  insideHorizontal: NONE,
  insideVertical: NONE,
};

type CellStyle = {
  width: number;
  fill?: string;
  margins?: [number, number, number, number];
  left?: { color: string; size: number };
  bottom?: string;
  gap?: number;
  vAlign?: "top" | "center" | "bottom";
  span?: number;
};

function cell(children: (Paragraph | Table)[], style: CellStyle) {
  const [top, right, bottom, left] = style.margins ?? [90, 120, 90, 120];
  const gap = style.gap
    ? { style: BorderStyle.SINGLE, size: style.gap, color: C.white }
    : NONE;
  return new TableCell({
    width: { size: style.width, type: WidthType.DXA },
    columnSpan: style.span,
    verticalAlign: style.vAlign ?? VerticalAlign.TOP,
    shading: style.fill
      ? { type: ShadingType.CLEAR, color: "auto", fill: style.fill }
      : undefined,
    margins: { top, right, bottom, left },
    borders: {
      top: gap,
      right: gap,
      bottom: style.bottom
        ? { style: BorderStyle.SINGLE, size: 4, color: style.bottom }
        : gap,
      left: style.left
        ? {
            style: BorderStyle.SINGLE,
            size: style.left.size,
            color: style.left.color,
          }
        : gap,
    },
    children,
  });
}

function table(widths: number[], rows: TableRow[]) {
  return new Table({
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
    borders: NO_BORDERS,
    rows,
  });
}

function spacer(after = 160) {
  return para([], { after, line: 120 });
}

function none(text: string) {
  return para([run(text, { size: 17, italics: true, color: C.muted })], {
    after: 60,
  });
}

// ---------- data helpers (exported for tests) ----------

export function clock(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function clip(text: string, max: number) {
  const value = text.replace(/\s+/g, " ").trim();
  if (value.length <= max) return value;
  const cut = value.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).trim()}…`;
}

function title(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export type VoiceSummary = {
  id: string;
  name: string;
  share: number;
  talkMs: number;
  questions: number;
  longestMs: number;
};

export function voices(input: ReportDocxInput): VoiceSummary[] {
  // Same labels as the app: "Speaker N" in the order voices first spoke.
  const firstSpoke: string[] = [];
  for (const segment of input.transcript?.segments ?? [])
    if (segment.speaker_id && !firstSpoke.includes(segment.speaker_id))
      firstSpoke.push(segment.speaker_id);
  const named = (id: string, index: number) => {
    const order = firstSpoke.indexOf(id);
    return (
      input.speakerName?.(id)?.trim() ||
      `Speaker ${(order < 0 ? index : order) + 1}`
    );
  };
  const recorded = input.callRecord?.numbers.speakers ?? [];
  if (recorded.length) {
    return recorded
      .map((speaker, index) => ({
        id: speaker.speaker_id,
        name: named(speaker.speaker_id, index),
        share: speaker.talk_share,
        talkMs: speaker.talk_ms,
        questions: speaker.questions,
        longestMs: speaker.longest_monologue_ms,
      }))
      .sort((a, b) => b.talkMs - a.talkMs);
  }
  const segments = input.transcript?.segments ?? [];
  const order: string[] = [];
  const talk = new Map<
    string,
    { ms: number; questions: number; longest: number }
  >();
  for (const segment of segments) {
    if (!segment.speaker_id) continue;
    if (!talk.has(segment.speaker_id)) {
      order.push(segment.speaker_id);
      talk.set(segment.speaker_id, { ms: 0, questions: 0, longest: 0 });
    }
    const item = talk.get(segment.speaker_id)!;
    const ms = Math.max(0, segment.end_ms - segment.start_ms);
    item.ms += ms;
    item.longest = Math.max(item.longest, ms);
    if (/[?？]\s*$/.test(segment.text)) item.questions += 1;
  }
  const total = [...talk.values()].reduce((sum, item) => sum + item.ms, 0) || 1;
  return order
    .map((id, index) => {
      const item = talk.get(id)!;
      return {
        id,
        name: named(id, index),
        share: item.ms / total,
        talkMs: item.ms,
        questions: item.questions,
        longestMs: item.longest,
      };
    })
    .sort((a, b) => b.talkMs - a.talkMs);
}

// Block lengths a reader can name; the smallest that keeps 30 blocks or fewer.
const BLOCKS = [15, 30, 60, 120, 180, 300, 600, 900, 1800].map((s) => s * 1000);

export function blockLabel(size: number) {
  return size < 60000 ? `${size / 1000} s` : `${size / 60000} min`;
}

/** Talk time per voice in equal blocks of the call (at most 30 blocks). */
export function talkSlices(
  transcript: Transcript | null | undefined,
  durationMs: number,
  ids: string[],
) {
  const size =
    BLOCKS.find((block) => Math.ceil(durationMs / block) <= 30) ??
    Math.ceil(durationMs / 30);
  const count = Math.max(1, Math.ceil(durationMs / size));
  const rows = ids.map(() => new Array<number>(count).fill(0));
  for (const segment of transcript?.segments ?? []) {
    const row = ids.indexOf(segment.speaker_id ?? "");
    if (row < 0) continue;
    for (
      let slice = Math.floor(segment.start_ms / size);
      slice < count && slice * size < segment.end_ms;
      slice += 1
    ) {
      const from = Math.max(segment.start_ms, slice * size);
      const to = Math.min(segment.end_ms, (slice + 1) * size);
      // The last block may be short; measure against its real length.
      const length = Math.min(size, durationMs - slice * size) || size;
      if (to > from) rows[row][slice] += (to - from) / length;
    }
  }
  return {
    count,
    size,
    rows: rows.map((row) => row.map((v) => Math.min(1, v))),
  };
}

export type DocMoment = {
  number: number;
  kind: "must" | "watch" | "repeat" | "done";
  label: string;
  text: string;
  quote: string | null;
  startMs: number;
};

export function moments(report: SalesReport): DocMoment[] {
  const overview = report.overview;
  const found: Omit<DocMoment, "number">[] = [];
  const kinds = {
    must_watch: ["must", "Must listen"],
    watch: ["watch", "Worth a listen"],
    repeat: ["repeat", "Do this again"],
  } as const;
  for (const item of overview?.rewatch ?? []) {
    const evidence = item.evidence[0];
    if (!evidence) continue;
    const [kind, label] = kinds[item.purpose];
    found.push({
      kind,
      label,
      text: item.text,
      quote: evidence.quote,
      startMs: evidence.start_ms,
    });
  }
  for (const item of overview?.golden_moments ?? []) {
    const strength = report.strengths[item.strength_index];
    const evidence = strength?.evidence[item.evidence_index];
    if (!evidence) continue;
    found.push({
      kind: "done",
      label: "Done well",
      text: item.why_effective || strength.title,
      quote: evidence.quote,
      startMs: evidence.start_ms,
    });
  }
  if (!found.length) {
    for (const finding of report.strengths.slice(0, 2)) {
      const evidence = finding.evidence[0];
      if (evidence)
        found.push({
          kind: "done",
          label: "Done well",
          text: finding.title,
          quote: evidence.quote,
          startMs: evidence.start_ms,
        });
    }
  }
  const seen = new Set<number>();
  return found
    .filter((item) =>
      seen.has(item.startMs) ? false : (seen.add(item.startMs), true),
    )
    .sort((a, b) => a.startMs - b.startMs)
    .slice(0, 6)
    .map((item, index) => ({ ...item, number: index + 1 }));
}

export type DocMissed = {
  letter: string;
  detailed: boolean;
  title: string;
  theySaid: string | null;
  youSaid: string | null;
  better: string;
  impact: string | null;
  startMs: number | null;
};

export function missedChances(report: SalesReport): DocMissed[] {
  const details = report.overview?.missed_details ?? [];
  const letters = "ABCDEF";
  if (details.length) {
    return details.slice(0, 3).map((detail, index) => {
      const finding = report.missed_opportunities[detail.finding_index];
      const evidence =
        detail.prospect_signal.evidence[0] ?? finding?.evidence[0];
      return {
        letter: letters[index],
        detailed: true,
        title: finding?.title ?? "Missed chance",
        theySaid: detail.prospect_signal.text || evidence?.quote || null,
        youSaid: detail.closer_response.text || null,
        better: detail.follow_up,
        impact: detail.potential_impact || null,
        startMs: evidence?.start_ms ?? null,
      };
    });
  }
  return report.missed_opportunities.slice(0, 3).map((finding, index) => ({
    letter: letters[index],
    detailed: false,
    title: finding.title,
    theySaid: finding.evidence[0]?.quote ?? null,
    youSaid: null,
    better: finding.explanation,
    impact: null,
    startMs: finding.evidence[0]?.start_ms ?? null,
  }));
}

const OUTCOME: Record<string, [string, string, string]> = {
  closed: ["Closed", C.teal, C.tealBg],
  follow_up: ["Follow-up set", C.blue, C.blueBg],
  future_date: ["Future date", C.blue, C.blueBg],
  no_sale: ["No sale", C.red, C.redBg],
  disqualified: ["Disqualified", C.muted, C.panel],
  unclear: ["Outcome unclear", C.amber, C.amberBg],
};

const DIMENSION: Record<string, [string, string]> = {
  observed: ["Observed", C.ink],
  insufficient_evidence: ["Not enough evidence", C.faint],
  not_applicable: ["Not applicable", C.faint],
  conflicted: ["Mixed signals", C.amber],
  unknown: ["Unknown", C.faint],
};

const MOMENT_COLOR: Record<DocMoment["kind"], string> = {
  must: C.red,
  watch: C.amber,
  repeat: C.teal,
  done: C.teal,
};

const FACT_TAG: [RegExp, string, string][] = [
  [/promis|commit/i, "Promise", C.blue],
  [/next[_ -]?step|follow/i, "Next step", C.teal],
  [/money|price|budget|income|profit|fee|cost/i, "Money", C.amber],
  [/person|people|name|family|role/i, "Person", C.voiceB],
];

function blend(hex: string, amount: number) {
  const t = Math.max(0, Math.min(1, amount));
  const channel = (i: number) => {
    const value = parseInt(hex.slice(i, i + 2), 16);
    return Math.round(255 + (value - 255) * t)
      .toString(16)
      .padStart(2, "0");
  };
  return `${channel(0)}${channel(2)}${channel(4)}`.toUpperCase();
}

// ---------- building blocks ----------

function kicker(text: string, color = C.muted) {
  return run(text, { size: 14, bold: true, color, caps: true, spacing: 16 });
}

/** Left and right text on one line. A borderless table, because tab stops
 * render differently in Word and in the in-app preview. */
function split(
  left: (TextRun | Bookmark)[],
  right: TextRun[],
  leftWidth: number,
  rule?: string,
  after = 70,
) {
  const side = (
    children: (TextRun | Bookmark)[],
    width: number,
    align?: ParaStyle["align"],
  ) =>
    cell([para(children, { align, keepNext: true, line: 240 })], {
      width,
      bottom: rule,
      vAlign: VerticalAlign.BOTTOM,
      margins: [0, 0, after, 0],
    });
  return table(
    [leftWidth, W - leftWidth],
    [
      new TableRow({
        cantSplit: true,
        children: [
          side(left, leftWidth),
          side(right, W - leftWidth, AlignmentType.RIGHT),
        ],
      }),
    ],
  );
}

function sectionTitle(
  text: string,
  note?: string,
  pageBreakBefore = false,
  bookmark?: string,
) {
  const label = run(text, { size: 23, bold: true, color: C.ink });
  return [
    para([], {
      before: pageBreakBefore ? 0 : 240,
      line: 120,
      pageBreakBefore,
      keepNext: true,
    }),
    split(
      [bookmark ? new Bookmark({ id: bookmark, children: [label] }) : label],
      note ? [run(note, { size: 15, color: C.muted })] : [],
      Math.round(W * 0.5),
      C.line,
    ),
    spacer(110),
  ];
}

function timeRun(ms: number | null, color = C.teal) {
  return ms === null
    ? run("")
    : run(`▶ ${clock(ms)}`, { size: 16, bold: true, color });
}

function quoteParagraph(
  quote: string | null,
  ms: number | null,
  color = C.teal,
) {
  if (!quote && ms === null) return null;
  const children: TextRun[] = [];
  if (ms !== null) children.push(timeRun(ms, color));
  if (quote)
    children.push(
      run(`${ms !== null ? "  " : ""}“${clip(quote, 170)}”`, {
        size: 16,
        italics: true,
        color: C.muted,
      }),
    );
  return para(children, { before: 60, line: 240 });
}

function header(input: ReportDocxInput) {
  const meta = [
    input.callDate,
    input.durationMs ? clock(input.durationMs) : null,
    input.callType ? title(input.callType) : null,
    input.language,
    ...(input.people ?? []),
  ].filter(Boolean) as string[];
  return [
    split(
      [kicker("Sales Xray  ·  Call review", C.teal)],
      [kicker("Draft coaching · not yet reviewed by a coach", C.faint)],
      Math.round(W * 0.4),
      undefined,
      80,
    ),
    para(
      [
        new Bookmark({
          id: "overview",
          children: [
            run(clip(input.title || "Untitled call", 90), {
              size: 40,
              bold: true,
              color: C.ink,
            }),
          ],
        }),
      ],
      { after: 40, line: 240 },
    ),
    para([run(meta.join("   ·   "), { size: 17, color: C.muted })], {
      after: 200,
      border: C.line,
    }),
  ];
}

function outcomeBand(report: SalesReport) {
  const overview = report.overview;
  const [label, color, fill] = OUTCOME[overview?.outcome?.kind ?? ""] ?? [
    "Verdict",
    C.ink,
    C.panel,
  ];
  const headline =
    overview?.final_assessment.assessment || report.verdict || report.summary;
  const right: Paragraph[] = [
    para([run(clip(headline, 420), { size: 21, bold: true, color: C.ink })], {
      line: 264,
    }),
  ];
  const outcome = overview?.outcome;
  if (report.summary && report.summary !== headline)
    right.push(
      para([run(clip(report.summary, 420), { size: 18, color: C.body })], {
        before: 70,
        line: 252,
      }),
    );
  if (outcome?.text) {
    const evidence = outcome.evidence[0];
    right.push(
      para(
        [
          run(clip(outcome.text, 260), { size: 17, color: C.muted }),
          ...(evidence ? [run("   "), timeRun(evidence.start_ms, color)] : []),
        ],
        { before: 70, line: 252 },
      ),
    );
  }
  return table(
    [2000, W - 2000],
    [
      new TableRow({
        cantSplit: true,
        children: [
          cell(
            [
              para([kicker("Outcome", color)], {
                align: AlignmentType.CENTER,
                after: 40,
              }),
              para([run(label, { size: 22, bold: true, color })], {
                align: AlignmentType.CENTER,
                line: 240,
              }),
            ],
            {
              width: 2000,
              fill,
              vAlign: VerticalAlign.CENTER,
              margins: [140, 100, 140, 100],
            },
          ),
          cell(right, {
            width: W - 2000,
            fill: C.panel,
            vAlign: VerticalAlign.CENTER,
            margins: [140, 200, 140, 200],
          }),
        ],
      }),
    ],
  );
}

function numbers(input: ReportDocxInput, list: VoiceSummary[]) {
  const duration =
    input.durationMs ??
    input.callRecord?.numbers.duration_ms ??
    input.transcript?.duration_ms ??
    0;
  const top = list.slice(0, 2);
  const items: [string, string, string][] = [
    ["Call length", duration ? clock(duration) : "—", "recording"],
    [
      "Talk share",
      top.length === 2
        ? `${Math.round(top[0].share * 100)} : ${Math.round(top[1].share * 100)}`
        : "—",
      top.length === 2
        ? `${clip(top[0].name, 18)} : ${clip(top[1].name, 18)}`
        : "not measured",
    ],
    [
      "Questions",
      top.length ? top.map((v) => v.questions).join(" : ") : "—",
      top.length === 2 ? "asked, same order" : "asked",
    ],
    [
      "Longest turn",
      list.length ? clock(Math.max(...list.map((v) => v.longestMs))) : "—",
      list.length
        ? clip(
            list.reduce((a, b) => (b.longestMs > a.longestMs ? b : a)).name,
            22,
          )
        : "",
    ],
    [
      "Talk-overs",
      input.callRecord ? String(input.callRecord.numbers.overlaps) : "—",
      "both speaking",
    ],
  ];
  const width = Math.floor(W / items.length);
  const widths = items.map((_, i) =>
    i === items.length - 1 ? W - width * (items.length - 1) : width,
  );
  return table(widths, [
    new TableRow({
      cantSplit: true,
      children: items.map(([label, value, note], i) =>
        cell(
          [
            para([kicker(label)], { after: 30 }),
            para([run(value, { size: 30, bold: true, color: C.ink })], {
              line: 240,
            }),
            para([run(note, { size: 14, color: C.muted })], {
              before: 20,
              line: 220,
            }),
          ],
          {
            width: widths[i],
            fill: C.panel,
            gap: 24,
            margins: [110, 140, 110, 140],
          },
        ),
      ),
    }),
  ]);
}

function talkBar(list: VoiceSummary[]) {
  const top = list.slice(0, 2);
  if (top.length < 2) return null;
  const total = top[0].share + top[1].share || 1;
  const first = Math.round(
    Math.min(0.85, Math.max(0.15, top[0].share / total)) * W,
  );
  const widths = [first, W - first];
  return table(widths, [
    new TableRow({
      height: { value: 300, rule: HeightRule.EXACT },
      children: top.map((voice, i) =>
        cell(
          [
            para(
              [
                run(
                  `${clip(voice.name, 24)}  ${Math.round((voice.share / total) * 100)}%`,
                  { size: 15, bold: true, color: C.white },
                ),
              ],
              {
                align: i ? AlignmentType.RIGHT : AlignmentType.LEFT,
                line: 240,
              },
            ),
          ],
          {
            width: widths[i],
            fill: i ? C.voiceB : C.voiceA,
            vAlign: VerticalAlign.CENTER,
            margins: [0, 120, 0, 120],
          },
        ),
      ),
    }),
  ]);
}

function timeline(
  input: ReportDocxInput,
  list: VoiceSummary[],
  marks: DocMoment[],
  missed: DocMissed[],
) {
  const duration = input.durationMs ?? input.transcript?.duration_ms ?? 0;
  const top = list.slice(0, 2);
  if (!duration || !top.length || !input.transcript?.segments.length) return [];
  const { count, size, rows } = talkSlices(
    input.transcript,
    duration,
    top.map((v) => v.id),
  );
  const labelWidth = 1500;
  const slice = Math.floor((W - labelWidth) / count);
  const widths = [
    labelWidth,
    ...Array.from({ length: count }, (_, i) =>
      i === count - 1 ? W - labelWidth - slice * (count - 1) : slice,
    ),
  ];
  const tiny = () => para([run("", { size: 2 })], { line: 120 });
  const voiceRow = (voice: VoiceSummary, index: number) =>
    new TableRow({
      height: { value: 230, rule: HeightRule.EXACT },
      children: [
        cell(
          [
            para(
              [
                run(clip(voice.name, 18), {
                  size: 14,
                  bold: true,
                  color: index ? C.voiceB : C.voiceA,
                }),
              ],
              { line: 220 },
            ),
          ],
          {
            width: labelWidth,
            vAlign: VerticalAlign.CENTER,
            margins: [0, 80, 0, 0],
          },
        ),
        ...rows[index].map((value, i) =>
          cell([tiny()], {
            width: widths[i + 1],
            fill:
              value > 0.02
                ? blend(index ? C.voiceB : C.voiceA, 0.18 + value * 0.82)
                : "F1F3F6",
            gap: 6,
            margins: [0, 0, 0, 0],
          }),
        ),
      ],
    });
  const slots = new Map<number, { text: string; color: string }>();
  for (const moment of marks) {
    const at = Math.min(count - 1, Math.floor(moment.startMs / size));
    if (!slots.has(at))
      slots.set(at, {
        text: String(moment.number),
        color: MOMENT_COLOR[moment.kind],
      });
  }
  for (const item of missed) {
    if (item.startMs === null) continue;
    const at = Math.min(count - 1, Math.floor(item.startMs / size));
    if (!slots.has(at)) slots.set(at, { text: item.letter, color: C.red });
  }
  const markRow = new TableRow({
    height: { value: 250, rule: HeightRule.EXACT },
    children: [
      cell([para([kicker("Moments")], { line: 220 })], {
        width: labelWidth,
        vAlign: VerticalAlign.CENTER,
        margins: [0, 80, 0, 0],
      }),
      ...widths.slice(1).map((width, i) => {
        const slot = slots.get(i);
        return cell(
          [
            slot
              ? para(
                  [run(slot.text, { size: 13, bold: true, color: C.white })],
                  { align: AlignmentType.CENTER, line: 220 },
                )
              : tiny(),
          ],
          {
            width,
            fill: slot?.color,
            gap: 6,
            vAlign: VerticalAlign.CENTER,
            margins: [0, 0, 0, 0],
          },
        );
      }),
    ],
  });
  // Axis: start, middle and end of the call under the strip.
  const thirds = [Math.floor(count / 3), Math.floor(count / 3)];
  thirds.push(count - thirds[0] - thirds[1]);
  const labels = [
    [run("0:00", { size: 14, color: C.faint }), AlignmentType.LEFT],
    [
      run(clock(duration / 2), { size: 14, color: C.faint }),
      AlignmentType.CENTER,
    ],
    [run(clock(duration), { size: 14, color: C.faint }), AlignmentType.RIGHT],
  ] as const;
  let from = 1;
  const axisRow = new TableRow({
    height: { value: 230, rule: HeightRule.EXACT },
    children: [
      cell([tiny()], { width: labelWidth, margins: [0, 0, 0, 0] }),
      ...thirds.map((span, i) => {
        const width = widths
          .slice(from, from + span)
          .reduce((a, b) => a + b, 0);
        from += span;
        return cell(
          [para([labels[i][0]], { align: labels[i][1], line: 220 })],
          {
            width,
            span,
            vAlign: VerticalAlign.BOTTOM,
            margins: [0, 0, 0, 0],
          },
        );
      }),
    ],
  });
  return [
    ...sectionTitle(
      "Who spoke, and when",
      `each block = ${blockLabel(size)} · darker = more talk`,
    ),
    table(widths, [...top.map(voiceRow), markRow, axisRow]),
  ];
}

function coachCards(report: SalesReport) {
  const overview = report.overview;
  const strength: Finding | undefined = report.strengths[0];
  const improvement: Finding | undefined =
    report.improvements[0] ?? report.missed_opportunities[0];
  const detail = overview?.improvement_details.find(
    (d) => d.finding_index === 0,
  );
  const why = overview?.strength_details.find(
    (d) => d.finding_index === 0,
  )?.why_it_matters;
  const gap = 200;
  const half = Math.floor((W - gap) / 2);
  const card = (
    label: string,
    color: string,
    fill: string,
    heading: string,
    lines: Paragraph[],
    evidence: ReportEvidence | undefined,
  ) => {
    const children = [
      para([kicker(label, color)], { after: 50 }),
      para([run(clip(heading, 160), { size: 21, bold: true, color: C.ink })], {
        after: 60,
        line: 252,
      }),
      ...lines,
    ];
    const quote = evidence
      ? quoteParagraph(evidence.quote, evidence.start_ms, color)
      : null;
    if (quote) children.push(quote);
    return cell(children, {
      width: half,
      fill,
      left: { color, size: 24 },
      margins: [150, 180, 150, 180],
    });
  };
  const keep = card(
    "Keep doing",
    C.teal,
    C.tealBg,
    overview?.final_assessment.repeat ||
      strength?.title ||
      "No strength supported yet",
    [
      para([run(clip(why || strength?.explanation || "", 340), { size: 18 })], {
        line: 252,
      }),
    ],
    strength?.evidence[0],
  );
  const fixLines = [
    para(
      [
        run(
          clip(detail?.why_it_matters || improvement?.explanation || "", 260),
          { size: 18 },
        ),
      ],
      { line: 252 },
    ),
  ];
  if (detail?.replacement_behavior)
    fixLines.push(
      para(
        [
          run("Try this: ", { size: 18, bold: true, color: C.amber }),
          run(clip(detail.replacement_behavior, 260), { size: 18 }),
        ],
        { before: 70, line: 252 },
      ),
    );
  const fix = card(
    "Fix first",
    C.amber,
    C.amberBg,
    overview?.final_assessment.fix_first ||
      improvement?.title ||
      "No change supported yet",
    fixLines,
    detail?.what_happened.evidence[0] ?? improvement?.evidence[0],
  );
  return table(
    [half, gap, W - half - gap],
    [
      new TableRow({
        cantSplit: true,
        children: [keep, cell([para([])], { width: gap }), fix],
      }),
    ],
  );
}

function nextCall(report: SalesReport) {
  const overview = report.overview;
  const behavior =
    overview?.next_call_focus?.behavior ||
    overview?.final_assessment.next_focus;
  if (!behavior) return null;
  const target = overview?.next_call_focus?.target;
  const children = [
    para([kicker("Next call · one thing", "7FD3C8")], { after: 60 }),
    para([run(clip(behavior, 240), { size: 23, bold: true, color: C.white })], {
      line: 264,
    }),
  ];
  if (target)
    children.push(
      para(
        [
          run("Done when: ", { size: 18, bold: true, color: "B9C4D6" }),
          run(clip(target, 240), { size: 18, color: "DCE3EE" }),
        ],
        { before: 80, line: 252 },
      ),
    );
  return table(
    [W],
    [
      new TableRow({
        cantSplit: true,
        children: [
          cell(children, {
            width: W,
            fill: C.ink,
            margins: [180, 240, 180, 240],
          }),
        ],
      }),
    ],
  );
}

function momentTable(list: DocMoment[], strip: boolean) {
  const title = sectionTitle(
    "Moments to replay",
    list.length && strip ? "numbers match the strip on page 1" : undefined,
    true,
    "moments",
  );
  if (!list.length)
    return [...title, none("No replay moments were marked for this call.")];
  const widths = [520, 1500, W - 520 - 1500];
  return [
    ...title,
    table(
      widths,
      list.map(
        (moment) =>
          new TableRow({
            cantSplit: true,
            children: [
              cell(
                [
                  para(
                    [
                      run(String(moment.number), {
                        size: 20,
                        bold: true,
                        color: C.white,
                      }),
                    ],
                    { align: AlignmentType.CENTER, line: 240 },
                  ),
                ],
                {
                  width: widths[0],
                  fill: MOMENT_COLOR[moment.kind],
                  vAlign: VerticalAlign.CENTER,
                  gap: 12,
                  margins: [60, 40, 60, 40],
                },
              ),
              cell(
                [
                  para(
                    [
                      run(clock(moment.startMs), {
                        size: 20,
                        bold: true,
                        color: C.ink,
                      }),
                    ],
                    { line: 240 },
                  ),
                  para([kicker(moment.label, MOMENT_COLOR[moment.kind])], {
                    before: 20,
                  }),
                ],
                {
                  width: widths[1],
                  bottom: C.line,
                  margins: [90, 120, 90, 160],
                },
              ),
              cell(
                [
                  para(
                    [
                      run(clip(moment.text, 220), {
                        size: 18,
                        bold: true,
                        color: C.ink,
                      }),
                    ],
                    { line: 252 },
                  ),
                  ...(moment.quote
                    ? [
                        para(
                          [
                            run(`“${clip(moment.quote, 200)}”`, {
                              size: 17,
                              italics: true,
                              color: C.muted,
                            }),
                          ],
                          { before: 40, line: 240 },
                        ),
                      ]
                    : []),
                ],
                {
                  width: widths[2],
                  bottom: C.line,
                  margins: [90, 120, 90, 120],
                },
              ),
            ],
          }),
      ),
    ),
  ];
}

function missedTable(list: DocMissed[]) {
  if (!list.length)
    return [
      ...sectionTitle("Missed chances", undefined, false, "missed"),
      none("No missed chances were flagged in this call."),
    ];
  // Older reports only have the finding; newer ones add what was said back
  // and a better answer, so the table drops the empty column for them.
  const detailed = list.some((item) => item.detailed);
  const rest = W - 520;
  const widths = detailed
    ? [
        520,
        Math.round(rest * 0.3),
        Math.round(rest * 0.3),
        rest - 2 * Math.round(rest * 0.3),
      ]
    : [520, Math.round(rest * 0.45), rest - Math.round(rest * 0.45)];
  const heads = detailed
    ? ["They said", "You said", "Better answer"]
    : ["They said", "What was missed"];
  const body = (children: Paragraph[], width: number, fill?: string) =>
    cell(children, {
      width,
      fill,
      bottom: C.line,
      margins: [90, 120, 90, 120],
    });
  return [
    ...sectionTitle(
      "Missed chances",
      detailed
        ? "what they said · what you said · a better answer"
        : "what they said · what was missed",
      false,
      "missed",
    ),
    table(widths, [
      new TableRow({
        tableHeader: true,
        children: [
          cell([para([])], { width: widths[0] }),
          ...heads.map((text, i) =>
            cell([para([kicker(text)])], {
              width: widths[i + 1],
              bottom: C.line,
              margins: [40, 120, 60, 120],
            }),
          ),
        ],
      }),
      ...list.map((item) => {
        const said = body(
          [
            para(
              [
                run(clip(item.title, 90), {
                  size: 17,
                  bold: true,
                  color: C.ink,
                }),
              ],
              { after: 30, line: 240 },
            ),
            para(
              [
                run(item.theySaid ? `“${clip(item.theySaid, 170)}”` : "—", {
                  size: 17,
                  italics: true,
                  color: C.body,
                }),
              ],
              { line: 240 },
            ),
            ...(item.startMs !== null
              ? [para([timeRun(item.startMs, C.red)], { before: 40 })]
              : []),
          ],
          widths[1],
        );
        const answer = (width: number, fill?: string) =>
          body(
            [
              para(
                [
                  run(clip(item.better, 260), {
                    size: 17,
                    bold: item.detailed,
                    color: C.ink,
                  }),
                ],
                { line: 240 },
              ),
              ...(item.impact
                ? [
                    para(
                      [
                        run(clip(item.impact, 160), {
                          size: 15,
                          color: C.muted,
                        }),
                      ],
                      { before: 40, line: 240 },
                    ),
                  ]
                : []),
            ],
            width,
            fill,
          );
        return new TableRow({
          cantSplit: true,
          children: [
            cell(
              [
                para(
                  [run(item.letter, { size: 20, bold: true, color: C.white })],
                  { align: AlignmentType.CENTER, line: 240 },
                ),
              ],
              {
                width: widths[0],
                fill: C.red,
                vAlign: VerticalAlign.CENTER,
                gap: 12,
                margins: [60, 40, 60, 40],
              },
            ),
            said,
            ...(detailed
              ? [
                  body(
                    [
                      para(
                        [
                          run(item.youSaid ? clip(item.youSaid, 200) : "—", {
                            size: 17,
                            color: C.body,
                          }),
                        ],
                        { line: 240 },
                      ),
                    ],
                    widths[2],
                  ),
                  answer(widths[3], C.tealBg),
                ]
              : [answer(widths[2])]),
          ],
        });
      }),
    ]),
  ];
}

function skillsTable(report: SalesReport) {
  const list = report.dimensions;
  if (!list.length)
    return [
      ...sectionTitle("Skills checked", undefined, false, "skills"),
      none("Skills were not checked for this call."),
    ];
  const widths = [2700, 1700, W - 4400];
  return [
    ...sectionTitle("Skills checked", undefined, false, "skills"),
    table(
      widths,
      list.map((dimension) => {
        const [status, color] = DIMENSION[dimension.status] ?? [
          "Unknown",
          C.faint,
        ];
        const evidence = dimension.evidence?.[0];
        return new TableRow({
          cantSplit: true,
          children: [
            cell(
              [
                para(
                  [
                    run(dimension.label, {
                      size: 17,
                      bold: true,
                      color: C.ink,
                    }),
                  ],
                  { line: 240 },
                ),
              ],
              { width: widths[0], bottom: C.line, margins: [70, 100, 70, 0] },
            ),
            cell(
              [
                para(
                  [
                    run("● ", { size: 15, color }),
                    run(status, { size: 15, bold: true, color }),
                  ],
                  { line: 240 },
                ),
              ],
              { width: widths[1], bottom: C.line, margins: [70, 100, 70, 100] },
            ),
            cell(
              [
                para(
                  [
                    run(clip(dimension.observation, 230), {
                      size: 16,
                      color: C.body,
                    }),
                    ...(evidence
                      ? [
                          run("  "),
                          run(clock(evidence.start_ms), {
                            size: 15,
                            bold: true,
                            color: C.teal,
                          }),
                        ]
                      : []),
                  ],
                  { line: 240 },
                ),
              ],
              { width: widths[2], bottom: C.line, margins: [70, 100, 70, 100] },
            ),
          ],
        });
      }),
    ),
  ];
}

function practiceBlock(report: SalesReport) {
  const practice = report.overview?.practice;
  if (!practice) return [];
  return [
    ...sectionTitle("Practice before the next call"),
    table(
      [W],
      [
        new TableRow({
          cantSplit: true,
          children: [
            cell(
              [
                para(
                  [
                    run(clip(practice.instructions, 420), {
                      size: 18,
                      color: C.body,
                    }),
                  ],
                  { line: 252 },
                ),
                para(
                  [
                    run("You have it when: ", {
                      size: 18,
                      bold: true,
                      color: C.teal,
                    }),
                    run(clip(practice.success_condition, 220), { size: 18 }),
                  ],
                  { before: 70, line: 252 },
                ),
              ],
              {
                width: W,
                fill: C.panel,
                left: { color: C.teal, size: 24 },
                margins: [130, 180, 130, 180],
              },
            ),
          ],
        }),
      ],
    ),
  ];
}

function factsTable(record: CallRecord | null | undefined) {
  const facts = (record?.facts ?? []).slice(0, 8);
  if (!facts.length)
    return [
      ...sectionTitle("Facts heard on the call", undefined, false, "facts"),
      none("No facts were recorded for this call."),
    ];
  const widths = [1300, W - 1300 - 900, 900];
  return [
    ...sectionTitle(
      "Facts heard on the call",
      "from the transcript, with times",
      false,
      "facts",
    ),
    table(
      widths,
      facts.map((fact) => {
        const probe = `${fact.tag ?? ""} ${fact.tag ? "" : fact.statement}`;
        const [, label, color] = FACT_TAG.find(([pattern]) =>
          pattern.test(probe),
        ) ?? [null, fact.tag ? title(fact.tag) : "Fact", C.muted];
        const evidence = fact.evidence[0];
        return new TableRow({
          cantSplit: true,
          children: [
            cell([para([kicker(label, color)], { line: 240 })], {
              width: widths[0],
              bottom: C.line,
              margins: [60, 80, 60, 0],
            }),
            cell(
              [
                para(
                  [run(clip(fact.statement, 200), { size: 17, color: C.body })],
                  { line: 240 },
                ),
              ],
              { width: widths[1], bottom: C.line, margins: [60, 100, 60, 100] },
            ),
            cell(
              [
                para(
                  [
                    run(evidence ? clock(evidence.start_ms) : "", {
                      size: 16,
                      bold: true,
                      color: C.teal,
                    }),
                  ],
                  { align: AlignmentType.RIGHT, line: 240 },
                ),
              ],
              {
                width: widths[2],
                bottom: C.line,
                margins: [60, 0, 60, 100],
              },
            ),
          ],
        });
      }),
    ),
  ];
}

function footer(input: ReportDocxInput) {
  const made = (input.generatedAt ?? new Date()).toISOString().slice(0, 10);
  const left = Math.round(W * 0.8);
  const side = (
    children: TextRun[],
    width: number,
    align?: ParaStyle["align"],
  ) =>
    cell([para(children, { align, line: 240 })], {
      width,
      margins: [70, 0, 0, 0],
    });
  return new Footer({
    children: [
      new Table({
        width: { size: W, type: WidthType.DXA },
        columnWidths: [left, W - left],
        layout: TableLayoutType.FIXED,
        borders: {
          ...NO_BORDERS,
          top: { style: BorderStyle.SINGLE, size: 4, color: C.line },
        },
        rows: [
          new TableRow({
            children: [
              side(
                [
                  run(
                    `Sales Xray · ${clip(input.title || "Call review", 60)} · made ${made} · times are recording times`,
                    { size: 14, color: C.faint },
                  ),
                ],
                left,
              ),
              side(
                [
                  new TextRun({
                    children: [
                      "Page ",
                      PageNumber.CURRENT,
                      " of ",
                      PageNumber.TOTAL_PAGES,
                    ],
                    font: FONT,
                    size: 14,
                    color: C.faint,
                  }),
                ],
                W - left,
                AlignmentType.RIGHT,
              ),
            ],
          }),
        ],
      }),
    ],
  });
}

export function buildReportDocument(input: ReportDocxInput) {
  const report = input.report;
  const list = voices(input);
  const marks = moments(report);
  const missed = missedChances(report);
  const bar = talkBar(list);
  const next = nextCall(report);
  const minutes = timeline(input, list, marks, missed);
  const replay = momentTable(marks, minutes.length > 0);
  const children: (Paragraph | Table)[] = [
    ...header(input),
    outcomeBand(report),
    spacer(200),
    numbers(input, list),
    ...(bar ? [spacer(120), bar] : []),
    ...minutes,
    ...sectionTitle("Coaching", undefined, false, "coaching"),
    coachCards(report),
    ...(next ? [spacer(200), next] : []),
    ...practiceBlock(report),
    ...replay,
    ...missedTable(missed),
    ...skillsTable(report),
    ...factsTable(input.callRecord),
  ];
  return new Document({
    creator: "Sales Xray",
    title: input.title || "Call review",
    description: "Sales Xray call review",
    styles: {
      default: {
        document: {
          run: { font: FONT, size: 19, color: C.body },
          paragraph: { spacing: { after: 0, line: 252 } },
        },
      },
    },
    sections: [
      {
        properties: {
          page: {
            size: { width: PAGE.width, height: PAGE.height },
            margin: {
              top: PAGE.margin,
              bottom: PAGE.margin,
              left: PAGE.margin,
              right: PAGE.margin,
              footer: 420,
            },
          },
        },
        footers: { default: footer(input) },
        children,
      },
    ],
  });
}

/** The one file the app previews and downloads. */
export function buildReportDocx(input: ReportDocxInput): Promise<Blob> {
  return buildPillarReportDocx(input);
}

export function documentInput(data: DocumentReportData): ReportDocxInput {
  if (!data.report) throw new Error("document_report_missing");
  const names = data.speakerNames ?? {};
  return {
    title: data.title || "Sales Xray call",
    callDate: data.callDate,
    callType: data.callType,
    durationMs:
      data.transcript?.duration_ms ??
      data.callRecord?.numbers.duration_ms ??
      null,
    report: data.report,
    transcript: data.transcript,
    callRecord: data.callRecord,
    speakerName: (id) => names[id],
    people: [
      data.repName ? `Rep: ${data.repName}` : null,
      data.prospectName ? `Prospect: ${data.prospectName}` : null,
    ].filter((item): item is string => Boolean(item)),
  };
}

export async function createReportDocx(
  data: DocumentReportData,
): Promise<Blob> {
  return buildReportDocx(documentInput(data));
}

export function reportDocxFilename(title = "Sales Xray call") {
  return `${title.replace(/[\u0000-\u001f<>:"/\\|?*]/g, " ").trim() || "Sales Xray call"} – Sales Xray report.docx`;
}
