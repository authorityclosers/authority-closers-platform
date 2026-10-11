import {
  AlignmentType,
  BorderStyle,
  Bookmark,
  Document,
  Footer,
  HeadingLevel,
  Packer,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableLayoutType,
  TableRow,
  TextRun,
  WidthType,
} from "docx";

import { COMMON, DOCUMENT } from "./report-copy";
import type { DocumentReportData } from "./report-document-data";
import {
  reportDocumentModel,
  type DocItem,
  type DocPeople,
  type DocTone,
  type ReportDoc,
} from "./report-document-model";

export { DOCUMENT_CHAPTERS } from "./report-document-data";

/**
 * The Word file: the Document view's own blocks written as a Word document,
 * so the download mirrors the page (and Dipak's document) heading for heading.
 * Pillars are Word headings (navigation pane) and keep their stable bookmarks.
 */

// Colours mirror the Lightbox light palette (lightbox/tokens.css).
const C = {
  ink: "0B1424",
  ink2: "1C2940",
  muted: "56637A",
  line: "E2E7F0",
  teal: "097870",
  tealSoft: "E6F2F1",
  warn: "B45309",
};
const TONE: Record<DocTone, string> = {
  good: C.teal,
  accent: C.teal,
  warn: C.warn,
  neutral: C.line,
};
const FONT = {
  ascii: "Calibri",
  hAnsi: "Calibri",
  eastAsia: "Calibri",
  cs: "Nirmala UI",
};
const PAGE = { width: 11906, height: 16838, margin: 1080 };
const WIDTH = PAGE.width - 2 * PAGE.margin;

const HAIR = { style: BorderStyle.SINGLE, size: 4, color: C.line };

type Run = {
  text: string;
  bold?: boolean;
  italics?: boolean;
  color?: string;
  size?: number;
  caps?: boolean;
};

const run = (value: Run) =>
  new TextRun({
    text: value.text,
    bold: value.bold,
    italics: value.italics,
    color: value.color,
    size: value.size,
    sizeComplexScript: value.size,
    allCaps: value.caps,
  });

function para(
  runs: Run[],
  options: {
    before?: number;
    after?: number;
    indent?: number;
    keepNext?: boolean;
    bullet?: boolean;
    border?: string;
  } = {},
) {
  return new Paragraph({
    children: runs.map(run),
    spacing: { before: options.before ?? 0, after: options.after ?? 100 },
    indent: options.indent ? { left: options.indent } : undefined,
    keepNext: options.keepNext,
    bullet: options.bullet ? { level: 0 } : undefined,
    border: options.border
      ? {
          left: {
            style: BorderStyle.SINGLE,
            size: 18,
            color: options.border,
            space: 8,
          },
        }
      : undefined,
  });
}

const possible = (on: boolean | undefined): Run[] =>
  on
    ? [
        {
          text: `  ${COMMON.possible}`,
          color: C.muted,
          size: 17,
          italics: true,
        },
      ]
    : [];

const timeRun = (text: string): Run => ({
  text,
  color: C.teal,
  bold: true,
  size: 19,
});

function cellOf(children: Paragraph[], width: number, shade?: string) {
  return new TableCell({
    children,
    width: { size: width, type: WidthType.DXA },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    borders: { top: HAIR, bottom: HAIR, left: HAIR, right: HAIR },
    shading: shade
      ? { type: ShadingType.CLEAR, color: "auto", fill: shade }
      : undefined,
  });
}

function tableOf(widths: number[], rows: TableRow[]) {
  return new Table({
    rows,
    width: { size: WIDTH, type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
  });
}

/** One block as Word paragraphs and tables, `indent` inside a card. */
function blocks(
  item: DocItem,
  indent = 0,
  border?: string,
): (Paragraph | Table)[] {
  const at = { indent, border };
  switch (item.type) {
    case "status":
      return [
        para(
          [
            {
              text: item.status,
              bold: true,
              size: 30,
              caps: true,
              color:
                item.tone === "warn"
                  ? C.warn
                  : item.tone === "neutral"
                    ? C.ink
                    : C.teal,
            },
            { text: `   ${item.origin}`, color: C.muted, size: 18 },
          ],
          { ...at, after: 120 },
        ),
      ];
    case "text":
      return [
        para(
          [
            { text: item.text, bold: item.strong },
            ...possible(item.possible),
            ...(item.clip ? [{ text: "   " }, timeRun(item.clip.at)] : []),
          ],
          at,
        ),
      ];
    case "label":
      return [
        para(
          [
            { text: item.text, bold: true, color: C.ink },
            ...possible(item.possible),
          ],
          { ...at, before: 80, after: 40, keepNext: true },
        ),
      ];
    case "list":
      return item.items.map((text) =>
        para([{ text }], { ...at, bullet: true, after: 40 }),
      );
    case "quote":
      return [
        ...(item.clip.speaker
          ? [
              para(
                [
                  {
                    text: item.clip.speaker,
                    bold: true,
                    size: 18,
                    color: C.ink,
                  },
                ],
                {
                  indent: indent + 240,
                  after: 0,
                  keepNext: true,
                  border: C.line,
                },
              ),
            ]
          : []),
        para([{ text: `“${item.clip.quote}”`, italics: true, color: C.ink2 }], {
          indent: indent + 240,
          border: C.line,
        }),
      ];
    case "play":
      return [para([timeRun(item.range ? item.clip.range : item.clip.at)], at)];
    case "metrics": {
      const width = Math.floor(WIDTH / Math.max(1, item.items.length));
      return [
        tableOf(
          item.items.map(() => width),
          [
            new TableRow({
              children: item.items.map((metric) =>
                cellOf(
                  [
                    para(
                      [
                        {
                          text: metric.value,
                          bold: true,
                          size: 30,
                          color: C.ink,
                        },
                      ],
                      { after: 0 },
                    ),
                    para([{ text: metric.label, size: 16, color: C.ink2 }], {
                      after: 0,
                    }),
                    ...(metric.note
                      ? [
                          para(
                            [{ text: metric.note, size: 15, color: C.muted }],
                            { after: 0 },
                          ),
                        ]
                      : []),
                  ],
                  width,
                ),
              ),
            }),
          ],
        ),
        para([{ text: item.note, color: C.muted, size: 17, italics: true }], {
          before: 80,
        }),
      ];
    }
    case "timeline":
      return item.stages.map((stage) =>
        para(
          [
            { text: `${stage.from}–${stage.to}   `, color: C.muted, size: 18 },
            { text: stage.label, bold: true },
          ],
          { after: 40 },
        ),
      );
    case "steps":
      return item.steps.flatMap((step, index) => [
        ...(index
          ? [para([{ text: "↓", color: C.muted }], { after: 0, indent: 240 })]
          : []),
        para(
          [
            {
              text: `${step.label}${step.title ? ` · ${step.title}` : ""}`,
              bold: true,
              caps: true,
              size: 17,
              color: index === 1 ? C.teal : C.ink,
            },
          ],
          { after: 0, keepNext: true, border: index === 1 ? C.teal : C.line },
        ),
        para([{ text: step.text }], { border: index === 1 ? C.teal : C.line }),
      ]);
    case "card": {
      const edge = TONE[item.tone];
      return [
        ...(item.kicker
          ? [
              para(
                [
                  {
                    text: item.kicker,
                    bold: true,
                    caps: true,
                    size: 17,
                    color: item.tone === "neutral" ? C.muted : edge,
                  },
                ],
                { before: 160, after: 0, keepNext: true, border: edge },
              ),
            ]
          : []),
        para([{ text: item.title, bold: true, size: 23, color: C.ink }], {
          before: item.kicker ? 0 : 160,
          after: 60,
          keepNext: true,
          border: edge,
        }),
        ...item.items.flatMap((inner) => blocks(inner, indent, edge)),
      ];
    }
    case "skills": {
      const widths = [Math.round(WIDTH * 0.27), Math.round(WIDTH * 0.2)];
      widths.push(WIDTH - widths[0] - widths[1]);
      return [
        tableOf(
          widths,
          item.rows.map(
            (row) =>
              new TableRow({
                cantSplit: true,
                children: [
                  cellOf(
                    [
                      para([{ text: row.name, bold: true, color: C.ink }], {
                        after: 0,
                      }),
                    ],
                    widths[0],
                  ),
                  cellOf(
                    [
                      para(
                        [
                          {
                            text: row.state,
                            bold: true,
                            color:
                              row.tone === "warn"
                                ? C.warn
                                : row.tone === "neutral"
                                  ? C.muted
                                  : C.teal,
                          },
                        ],
                        { after: 0 },
                      ),
                    ],
                    widths[1],
                  ),
                  cellOf(
                    [
                      para([{ text: row.observation }], {
                        after: row.clips.length ? 40 : 0,
                      }),
                      ...(row.clips.length
                        ? [
                            para(
                              row.clips.flatMap((clip, i) => [
                                ...(i
                                  ? [{ text: "  ·  ", color: C.muted }]
                                  : []),
                                timeRun(clip.at),
                              ]),
                              { after: 0 },
                            ),
                          ]
                        : []),
                    ],
                    widths[2],
                  ),
                ],
              }),
          ),
        ),
      ];
    }
    case "summary": {
      const width = Math.floor(WIDTH / Math.max(1, item.cells.length));
      return [
        tableOf(
          item.cells.map(() => width),
          [
            new TableRow({
              children: item.cells.map((cell) =>
                cellOf(
                  [
                    para(
                      [
                        {
                          text: cell.label,
                          bold: true,
                          caps: true,
                          size: 15,
                          color: C.muted,
                        },
                      ],
                      { after: 20 },
                    ),
                    para(
                      [
                        {
                          text: cell.value,
                          bold: true,
                          size: 18,
                          color: C.ink,
                        },
                      ],
                      { after: 0 },
                    ),
                  ],
                  width,
                  C.tealSoft,
                ),
              ),
            }),
          ],
        ),
      ];
    }
  }
}

function header(doc: ReportDoc): Paragraph[] {
  return [
    para(
      [{ text: doc.kicker, bold: true, caps: true, size: 17, color: C.teal }],
      { after: 60 },
    ),
    new Paragraph({
      heading: HeadingLevel.TITLE,
      children: [run({ text: doc.title, bold: true, size: 44, color: C.ink })],
      spacing: { after: 100 },
    }),
    ...(doc.facts.length
      ? [
          para(
            doc.facts.flatMap((fact, index) => [
              ...(index ? [{ text: "   ·   ", color: C.muted, size: 18 }] : []),
              { text: `${fact.label} `, color: C.muted, size: 18 },
              { text: fact.value, bold: true, size: 18, color: C.ink },
            ]),
            { after: 60 },
          ),
        ]
      : []),
    para([{ text: doc.draftNote, italics: true, color: C.muted, size: 18 }], {
      after: 200,
    }),
  ];
}

/** The Word document for one report, from the same blocks as the page. */
export function buildReportDocument(doc: ReportDoc) {
  const children: (Paragraph | Table)[] = [...header(doc)];
  for (const section of doc.sections) {
    children.push(
      new Paragraph({
        heading: HeadingLevel.HEADING_1,
        children: [
          new Bookmark({
            id: section.id,
            children: [
              run({
                text: section.heading,
                bold: true,
                size: 30,
                color: C.ink,
                caps: true,
              }),
            ],
          }),
        ],
        spacing: { before: 360, after: 40 },
        keepNext: true,
      }),
      new Paragraph({
        children: [run({ text: section.subtitle, bold: true, color: C.ink2 })],
        spacing: { after: 160 },
        border: {
          bottom: {
            style: BorderStyle.SINGLE,
            size: 12,
            color: C.teal,
            space: 6,
          },
        },
        keepNext: true,
      }),
    );
    for (const part of section.parts) {
      if (part.heading)
        children.push(
          new Paragraph({
            heading: HeadingLevel.HEADING_2,
            children: [
              run({ text: part.heading, bold: true, size: 24, color: C.ink }),
            ],
            spacing: { before: 200, after: 60 },
            keepNext: true,
          }),
        );
      for (const item of part.items) children.push(...blocks(item));
    }
    if (section.gaps.length)
      children.push(
        para(
          [
            {
              text: `${COMMON.gapsLead} `,
              bold: true,
              color: C.muted,
              size: 18,
            },
            { text: section.gaps.join(" · "), color: C.muted, size: 18 },
          ],
          { before: 120 },
        ),
      );
  }
  if (doc.summary)
    children.push(
      para([{ text: "" }], { before: 200, after: 0 }),
      ...blocks(doc.summary),
    );
  children.push(
    para([{ text: doc.closing, color: C.ink2, size: 18 }], { before: 240 }),
  );

  return new Document({
    creator: "Sales Xray",
    title: doc.title,
    description: DOCUMENT.kicker,
    styles: {
      default: {
        document: {
          run: { font: FONT, size: 21, sizeComplexScript: 21, color: C.ink2 },
          paragraph: { spacing: { line: 276 } },
        },
        title: { run: { font: FONT, color: C.ink } },
        heading1: { run: { font: FONT, color: C.ink } },
        heading2: { run: { font: FONT, color: C.ink } },
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
              footer: 480,
            },
          },
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  run({
                    text: `${DOCUMENT.footer}   ·   `,
                    color: C.muted,
                    size: 16,
                  }),
                  new TextRun({
                    children: [PageNumber.CURRENT],
                    color: C.muted,
                    size: 16,
                  }),
                ],
              }),
            ],
          }),
        },
        children,
      },
    ],
  });
}

export function buildReportDocx(doc: ReportDoc): Promise<Blob> {
  return Packer.toBlob(buildReportDocument(doc));
}

/** The one Word file the Document view downloads. */
export async function createReportDocx(
  data: DocumentReportData,
  people?: DocPeople,
): Promise<Blob> {
  return buildReportDocx(reportDocumentModel(data, people));
}

export function reportDocxFilename(title = "Sales Xray call") {
  const safe =
    title.replace(/[\u0000-\u001f<>:"/\\|?*]/g, " ").trim() ||
    "Sales Xray call";
  return `${safe} – ${DOCUMENT.fileName}.docx`;
}

/** Recording time as m:ss (h:mm:ss past an hour). */
export function clock(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const tail = String(total % 60).padStart(2, "0");
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${tail}`
    : `${minutes}:${tail}`;
}
