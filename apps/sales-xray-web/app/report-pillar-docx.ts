import { Bookmark, Document, Footer, Packer, Paragraph, TextRun } from "docx";
import type { ReportDocxInput } from "./report-docx";
import { reportPillars } from "./report-pillars";

const FONT = {
  ascii: "Calibri",
  hAnsi: "Calibri",
  eastAsia: "Calibri",
  cs: "Nirmala UI",
};
const clock = (ms: number) => {
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const tail = String(seconds % 60).padStart(2, "0");
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${tail}`
    : `${minutes}:${tail}`;
};

/** Six call-level pillars; coaching and full prospect facts stay out. */
export function buildPillarReportDocument(input: ReportDocxInput) {
  const children: Paragraph[] = [
    new Paragraph({
      children: [
        new TextRun({
          text: input.title || "Sales Xray call report",
          bold: true,
          size: 36,
        }),
      ],
      spacing: { after: 100 },
    }),
    new Paragraph({
      text: "Draft call analysis · not yet reviewed by a coach",
      spacing: { after: 100 },
    }),
    new Paragraph({
      text: [
        input.callDate,
        input.callType,
        input.durationMs ? `Call length ${clock(input.durationMs)}` : null,
        ...(input.people ?? []),
      ]
        .filter(Boolean)
        .join(" · "),
      spacing: { after: 160 },
    }),
  ];
  reportPillars(
    input.report,
    input.durationMs ?? input.transcript?.duration_ms,
  ).forEach((pillar, index) => {
    children.push(
      new Paragraph({
        children: [
          new Bookmark({
            id: pillar.id,
            children: [
              new TextRun({
                text: `${index + 1}. ${pillar.label}`,
                bold: true,
                size: 26,
              }),
            ],
          }),
        ],
        spacing: { before: 240, after: 120 },
        keepNext: true,
      }),
    );
    if (index === 1) {
      const numbers = input.callRecord?.numbers;
      if (numbers) {
        children.push(
          new Paragraph({
            text: "Call measurements · evidence, not a performance judgement",
            spacing: { after: 80 },
          }),
        );
        numbers.speakers.forEach((speaker, voice) => {
          const name =
            input.speakerName?.(speaker.speaker_id) || `Speaker ${voice + 1}`;
          children.push(
            new Paragraph({
              text: `${name} · Talk share ${Math.round(speaker.talk_share * 100)}% · Questions ${speaker.questions}`,
              spacing: { after: 60 },
            }),
          );
        });
        if (numbers.speakers.length < 2)
          children.push(
            new Paragraph({
              text: "Only one speaker is represented. A seller–prospect comparison is unavailable.",
              spacing: { after: 80 },
            }),
          );
      } else
        children.push(
          new Paragraph({
            text: "Call measurements were not supplied for this report.",
            spacing: { after: 80 },
          }),
        );
    }
    pillar.timeline?.forEach((phase) => {
      children.push(
        new Paragraph({
          text: `${clock(phase.start_ms)}–${clock(phase.end_ms)} · ${phase.label}`,
          spacing: { after: 60 },
        }),
      );
    });
    pillar.entries.forEach((entry) => {
      children.push(
        new Paragraph({
          children: [
            new TextRun({ text: entry.label, bold: true }),
            new TextRun({
              text: entry.hypothesis
                ? " · Interpretation"
                : entry.gap
                  ? " · Information gap"
                  : "",
            }),
          ],
          spacing: { before: 100, after: 40 },
          keepNext: true,
        }),
      );
      children.push(
        new Paragraph({
          text: entry.text,
          spacing: { after: 60 },
          keepLines: true,
        }),
      );
      for (const evidence of entry.evidence)
        children.push(
          new Paragraph({
            children: [
              new TextRun({
                text: `${clock(evidence.start_ms)}–${clock(evidence.end_ms)} · “${evidence.quote}”`,
                italics: true,
              }),
            ],
            spacing: { after: 60 },
            keepLines: true,
          }),
        );
    });
  });
  children.push(
    new Paragraph({
      text: "View Prospect Information in Sales Xray. Personalized Coaching is not available from this report export.",
      spacing: { before: 200 },
    }),
  );
  return new Document({
    creator: "Sales Xray",
    title: input.title || "Call review",
    description: "Sales Xray six-pillar call report",
    styles: {
      default: {
        document: {
          run: { font: FONT, size: 20, sizeComplexScript: 20, color: "2B3645" },
          paragraph: { spacing: { line: 260 } },
        },
      },
    },
    sections: [
      {
        properties: {
          page: {
            size: { width: 11906, height: 16838 },
            margin: {
              top: 850,
              bottom: 850,
              left: 850,
              right: 850,
              footer: 420,
            },
          },
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                text: "Sales Xray · Draft call analysis · Times are recording times",
              }),
            ],
          }),
        },
        children,
      },
    ],
  });
}

export function buildPillarReportDocx(input: ReportDocxInput): Promise<Blob> {
  return Packer.toBlob(buildPillarReportDocument(input));
}
