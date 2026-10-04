import {
  AlignmentType,
  Bookmark,
  BorderStyle,
  Document,
  Footer,
  Header,
  HeadingLevel,
  LevelFormat,
  LineRuleType,
  Packer,
  PageNumber,
  Paragraph,
  Table,
  TableCell,
  TableLayoutType,
  TableRow,
  TextRun,
  WidthType,
} from "docx";
import type { Finding, ReportEvidence } from "./report-contract";

import {
  DOCUMENT_CHAPTERS,
  type DocumentReportData,
} from "./report-document-data";
export { DOCUMENT_CHAPTERS } from "./report-document-data";
const NAVY = "16283F",
  GOLD = "B8862E",
  MUTED = "6B6B6B";
const WIDTH = 9758; // A4 less two 1.9 cm margins, in twips.
const border = { style: BorderStyle.SINGLE, size: 4, color: "DDDDDA" };

function time(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
function body(text: string) {
  return new Paragraph({ text, style: "BodyText", widowControl: true });
}
function heading(text: string) {
  return new Paragraph({ text, heading: HeadingLevel.HEADING_2 });
}
function chapter(id: string, label: string) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    pageBreakBefore: true,
    children: [new Bookmark({ id, children: [new TextRun(label)] })],
  });
}
function table(headers: string[], rows: string[][], widths: number[]) {
  const row = (values: string[], header: boolean, index: number) =>
    new TableRow({
      ...(header ? { tableHeader: true } : {}),
      cantSplit: true,
      children: values.map(
        (text, i) =>
          new TableCell({
            width: { size: widths[i], type: WidthType.DXA },
            shading: { fill: header ? NAVY : index % 2 ? "FFFFFF" : "F2F2F0" },
            children: [
              new Paragraph({
                style: "BodyText",
                spacing: { after: 60 },
                children: [
                  new TextRun({
                    text,
                    bold: header,
                    color: header ? "FFFFFF" : "222222",
                  }),
                ],
              }),
            ],
          }),
      ),
    });
  return new Table({
    width: { size: WIDTH, type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
    margins: { top: 120, bottom: 120, left: 150, right: 150 },
    borders: {
      top: border,
      bottom: border,
      left: border,
      right: border,
      insideHorizontal: border,
      insideVertical: border,
    },
    rows: [
      row(headers, true, 0),
      ...rows.map((values, i) => row(values, false, i)),
    ],
  });
}
function callout(title: string, text: string, fill = "F2F2F0", color = NAVY) {
  return new Table({
    width: { size: WIDTH, type: WidthType.DXA },
    columnWidths: [WIDTH],
    margins: { top: 180, bottom: 160, left: 220, right: 220 },
    borders: {
      top: border,
      bottom: border,
      left: { ...border, size: 16, color },
      right: border,
    },
    rows: [
      new TableRow({
        cantSplit: true,
        children: [
          new TableCell({
            shading: { fill },
            children: [
              new Paragraph({
                style: "BodyText",
                children: [new TextRun({ text: title, bold: true, color })],
              }),
              body(text),
            ],
          }),
        ],
      }),
    ],
  });
}
function findings(items: Finding[], fill: string, color = NAVY) {
  return items.length
    ? items.flatMap((f) => [
        callout(f.title, f.explanation, fill, color),
        body(""),
      ])
    : [body("No findings supplied in this report.")];
}
function list(items: string[]) {
  return items.map(
    (text) =>
      new Paragraph({
        text,
        style: "BodyText",
        numbering: { reference: "report-list", level: 0 },
      }),
  );
}

/** Export supplied report fields only. No scoring, role inference or provider call. */
export async function createReportDocx(
  data: DocumentReportData,
): Promise<Blob> {
  if (!data.report) throw new Error("document_report_missing");
  const report = data.report,
    overview = report.overview;
  const evidence: ReportEvidence[] = [];
  // Overview contains additional source notes; retain all supplied quotes exactly.
  function collect(value: unknown) {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) {
      value.forEach(collect);
      return;
    }
    const object = value as Record<string, unknown>;
    if (
      typeof object.segment_id === "string" &&
      typeof object.quote === "string" &&
      typeof object.start_ms === "number" &&
      typeof object.end_ms === "number"
    ) {
      evidence.push(object as ReportEvidence);
    } else Object.values(object).forEach(collect);
  }
  collect(report);
  const quotes = [
    ...new Map(
      evidence.map((e) => [
        `${e.segment_id}:${e.start_ms}:${e.end_ms}:${e.quote}`,
        e,
      ]),
    ).values(),
  ].sort((a, b) => a.start_ms - b.start_ms);
  const title = data.title || "Sales Xray call";
  const children: (Paragraph | Table)[] = [
    new Paragraph({
      text: "AUTHORITY CLOSERS  /  SALES XRAY",
      style: "Kicker",
    }),
    new Paragraph({ text: title, heading: HeadingLevel.TITLE }),
    new Paragraph({ text: "Sales Xray report", style: "Subtitle" }),
    table(
      ["Call details", "Source"],
      [
        ...Object.entries({
          Workspace: data.workspaceName,
          Seller: data.repName,
          Prospect: data.prospectName,
          "Call type": data.callType,
          Date: data.callDate,
          Duration: data.callLength,
          Analysed: data.analysedDate,
        }).filter((entry): entry is [string, string] => Boolean(entry[1])),
        ["Source", report.source_label],
        ["Transcript revision", report.transcript_revision],
        ["Review status", "Draft · not human-adjudicated"],
        ...Object.entries(data.analysisBasis ?? {})
          .filter((entry): entry is [string, string] => Boolean(entry[1]))
          .filter(
            ([key, value]) =>
              !(
                key === "transcriptRevision" &&
                value === report.transcript_revision
              ) && !(key === "recordingLength" && value === data.callLength),
          )
          .map(([key, value]) => [
            (
              {
                recordingLength: "Recording length",
                transcriptRevision: "Transcript revision",
                analysisVersion: "Analysis version",
              } as Record<string, string>
            )[key],
            value,
          ]),
      ],
      [2600, WIDTH - 2600],
    ),
    body(""),
    callout("Overall verdict", report.verdict),
    heading("In this document"),
    ...list(DOCUMENT_CHAPTERS.map((c) => c.label)),
    chapter("overview", "Overview"),
    heading("Call summary"),
    body(report.summary),
    ...(overview?.diagnosis
      ? [callout("Diagnosis", overview.diagnosis.text)]
      : []),
    ...(overview?.outcome
      ? [heading("Call outcome"), body(overview.outcome.text)]
      : []),
    heading("Strengths"),
    ...findings(report.strengths, "EAF3EC"),
    ...(overview?.strength_details.flatMap((d) => [
      heading("Why it matters"),
      body(d.why_it_matters),
    ]) ?? []),
    heading("Development areas"),
    ...findings(report.improvements, "FBEFE6", "B33A3A"),
    chapter("moments", "Moments"),
    heading("Detailed source evidence"),
    ...(quotes.length
      ? [
          table(
            ["Timestamp", "Source quote", "Segment"],
            quotes.map((e) => [
              `${time(e.start_ms)}–${time(e.end_ms)}`,
              e.quote,
              e.segment_id,
            ]),
            [1500, 6458, 1800],
          ),
        ]
      : [body("No source quotes supplied.")]),
    ...(overview?.golden_moments.flatMap((m) => [
      heading("Why this moment was effective"),
      body(m.why_effective),
    ]) ?? []),
    ...(overview?.rewatch.flatMap((r) => [
      heading("Rewatch"),
      body(r.text),
      body(`Purpose: ${r.purpose}`),
    ]) ?? []),
    chapter("analysis", "Analysis"),
    heading("Capability evidence"),
    body(
      "Numeric scores are not supplied. Observation states are retained from the report.",
    ),
    table(
      ["Dimension", "Score", "Note"],
      report.dimensions.map((d) => [
        d.label,
        "Not scored",
        `${d.status.replaceAll("_", " ")} — ${d.observation}`,
      ]),
      [2500, 1300, WIDTH - 3800],
    ),
    heading("Missed opportunities"),
    ...findings(report.missed_opportunities, "FBEFE6"),
    ...(overview?.missed_details.flatMap((d) => [
      heading("Prospect signal"),
      body(d.prospect_signal.text),
      heading("Seller response"),
      body(d.closer_response.text),
      heading("Suggested follow-up"),
      body(d.follow_up),
      heading("Potential impact"),
      body(d.potential_impact),
    ]) ?? []),
    heading("Objections"),
    ...findings(report.objection_analysis, "F2F2F0"),
    heading("Closing analysis"),
    ...findings(report.closing_analysis, "F2F2F0"),
    ...(overview?.prospect_interpretations.flatMap((p) => [
      heading("Prospect interpretation · inference"),
      body(p.source.text),
      body(p.possible_concern),
    ]) ?? []),
    ...(overview?.conversation_change
      ? [
          heading("Conversation change · inference"),
          body(overview.conversation_change.before.text),
          body(overview.conversation_change.change.text),
          body(overview.conversation_change.after.text),
          body(overview.conversation_change.possible_effect),
        ]
      : []),
    ...(overview?.business_impact
      ? [
          heading("Business impact · insufficient data"),
          ...list(overview.business_impact.missing_inputs),
        ]
      : []),
    chapter("coaching", "Coaching"),
    ...(overview?.improvement_details.flatMap((d) => [
      heading("What happened"),
      body(d.what_happened.text),
      heading("Why it matters"),
      body(d.why_it_matters),
      callout("Replacement behavior", d.replacement_behavior, "FBEFE6"),
      heading("Business impact · insufficient data"),
      ...list(d.business_impact.missing_inputs),
    ]) ?? []),
    ...(overview?.ethics_notes.flatMap((n) => [
      callout("Risk / ethics note", n.text, "FBEFE6", "B33A3A"),
      body(""),
    ]) ?? []),
    ...(overview?.next_call_focus
      ? [
          callout(
            "Next-call focus",
            overview.next_call_focus.behavior,
            "EAF3EC",
          ),
          heading("Target"),
          body(overview.next_call_focus.target),
        ]
      : []),
    ...(overview?.practice
      ? [
          heading("Practice"),
          ...list([
            overview.practice.instructions,
            overview.practice.success_condition,
          ]),
        ]
      : []),
    ...(overview?.final_assessment
      ? [
          heading("Final assessment"),
          ...list([
            overview.final_assessment.repeat,
            overview.final_assessment.fix_first,
            overview.final_assessment.next_focus,
          ]),
          body(overview.final_assessment.assessment),
        ]
      : [body(report.verdict)]),
    ...(report.preview
      ? [
          body(
            "Preview report: additional findings have not been supplied. Sign in to view the full report.",
          ),
        ]
      : []),
    chapter("transcript", "Transcript appendix"),
    ...(data.transcript?.segments.flatMap((s) => [
      heading(
        `${time(s.start_ms)}–${time(s.end_ms)} · ${s.speaker_id ?? "Speaker not supplied"}`,
      ),
      body(s.text),
    ]) ?? [body("Transcript not supplied.")]),
  ];
  return Packer.toBlob(
    new Document({
      title: `${title} – Sales Xray report`,
      creator: "Authority Closers",
      styles: {
        default: {
          document: {
            run: { font: "Calibri", size: 21, color: "222222" },
            paragraph: {
              spacing: { after: 100, line: 276 },
            },
          },
          title: {
            run: { size: 52, bold: true, color: NAVY },
            paragraph: {
              keepNext: true,
              spacing: {
                before: 600,
                after: 240,
                line: 600,
                lineRule: LineRuleType.EXACT,
              },
            },
          },
          heading1: {
            run: { size: 30, bold: true, color: NAVY },
            paragraph: {
              keepNext: true,
              keepLines: true,
              spacing: { after: 240 },
              border: {
                bottom: {
                  style: BorderStyle.SINGLE,
                  color: GOLD,
                  size: 12,
                  space: 8,
                },
              },
            },
          },
          heading2: {
            run: { size: 24, bold: true, color: "1F3A5F" },
            paragraph: {
              keepNext: true,
              keepLines: true,
              spacing: { before: 180, after: 120 },
            },
          },
        },
        paragraphStyles: [
          {
            id: "BodyText",
            name: "Body Text",
            basedOn: "Normal",
            next: "BodyText",
            quickFormat: true,
          },
          {
            id: "Kicker",
            name: "Kicker",
            basedOn: "Normal",
            run: { size: 18, color: GOLD, bold: true },
            paragraph: { keepNext: true },
          },
          {
            id: "Subtitle",
            name: "Subtitle",
            basedOn: "Normal",
            run: { size: 28, color: MUTED },
            paragraph: { keepNext: true, spacing: { after: 400 } },
          },
        ],
      },
      numbering: {
        config: [
          {
            reference: "report-list",
            levels: [
              {
                level: 0,
                format: LevelFormat.BULLET,
                text: "•",
                alignment: AlignmentType.LEFT,
                style: { paragraph: { indent: { left: 360, hanging: 180 } } },
              },
            ],
          },
        ],
      },
      sections: [
        {
          properties: {
            page: {
              size: { width: 11906, height: 16838 },
              margin: {
                top: 1074,
                bottom: 1074,
                left: 1074,
                right: 1074,
                header: 480,
                footer: 480,
              },
            },
          },
          headers: {
            default: new Header({
              children: [
                new Paragraph({
                  children: [
                    new TextRun({
                      text: `Sales Xray · ${title}`,
                      size: 16,
                      color: MUTED,
                    }),
                  ],
                }),
              ],
            }),
          },
          footers: {
            default: new Footer({
              children: [
                new Paragraph({
                  alignment: AlignmentType.RIGHT,
                  children: [
                    new TextRun({
                      children: [
                        "Authority Closers  ·  Page ",
                        PageNumber.CURRENT,
                        " of ",
                        PageNumber.TOTAL_PAGES,
                      ],
                      size: 16,
                      color: MUTED,
                    }),
                  ],
                }),
              ],
            }),
          },
          children,
        },
      ],
    }),
  );
}

export function reportDocxFilename(title = "Sales Xray call") {
  return `${title.replace(/[\u0000-\u001f<>:"/\\|?*]/g, " ").trim() || "Sales Xray call"} – Sales Xray report.docx`;
}
