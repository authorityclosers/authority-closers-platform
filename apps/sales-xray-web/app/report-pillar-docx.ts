import { Bookmark, Document, Footer, Packer, Paragraph, TextRun } from "docx";
import type { ReportEvidence } from "./report-contract";
import type { ReportDocxInput } from "./report-docx";
import { REPORT_PILLARS } from "./report-pillars";
import { reportStoryModel, type StoryModel } from "./report-story-model";

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

type Entry = {
  label: string;
  text: string;
  evidence?: ReportEvidence[];
  inferred?: boolean;
};

/** The same six-pillar story as the screen, as plain labelled entries. */
function storyEntries(model: StoryModel): Entry[][] {
  const { picture, flow, deal } = model;
  const line = (
    label: string,
    value: {
      text: string;
      sources: ReportEvidence[];
      inferred?: boolean;
    } | null,
  ): Entry[] =>
    value
      ? [
          {
            label,
            text: value.text,
            evidence: value.sources.slice(0, 1),
            inferred: value.inferred,
          },
        ]
      : [];
  const status = picture.outcome.status
    ? `${picture.outcome.status} · ${picture.outcome.origin === "person" ? "recorded by your team" : "as heard on the call"}`
    : "Outcome not recorded · only a person records won or lost";
  return [
    [
      { label: "Call outcome", text: status },
      ...line("Summary", picture.summary),
      ...(picture.assessment
        ? [{ label: "In short", text: picture.assessment }]
        : []),
      ...line("What most affected this call", picture.influence),
      ...line("Strongest part", picture.strongest),
      ...line("Biggest concern", picture.concern),
      ...line("Next step", picture.nextStep),
    ],
    [
      ...(flow.metrics.length
        ? [
            {
              label: "Call measurements · evidence, not a judgement",
              text: flow.metrics
                .map(
                  (metric) =>
                    `${metric.label} ${metric.value}${metric.note ? ` (${metric.note})` : ""}`,
                )
                .join(" · "),
            },
          ]
        : []),
      ...(flow.phases ?? []).map((phase) => ({
        label: `${clock(phase.start_ms)}–${clock(phase.end_ms)}`,
        text: phase.label,
      })),
      ...(flow.change
        ? [
            { label: "Before", text: flow.change.before.text },
            {
              label: "The switch",
              text: flow.change.turn.text,
              evidence: flow.change.turn.sources.slice(0, 1),
            },
            { label: "After", text: flow.change.after.text },
            ...(flow.change.effect
              ? [
                  {
                    label: "Possible effect",
                    text: flow.change.effect,
                    inferred: true,
                  },
                ]
              : []),
          ]
        : []),
    ],
    [
      ...model.worked.map((item) => ({
        label: `What worked · ${item.title}`,
        text: [
          item.what.text,
          item.why ? `Why it helped: ${item.why.text}` : "",
        ]
          .filter(Boolean)
          .join(" "),
        evidence: item.what.sources,
      })),
      ...model.didnt.map((item) => ({
        label: `What didn't · ${item.title}`,
        text: [
          item.what.text,
          item.why ? `What it affected: ${item.why.text}` : "",
        ]
          .filter(Boolean)
          .join(" "),
        evidence: item.what.sources,
      })),
    ],
    [...model.moments]
      .sort((a, b) => a.source.start_ms - b.source.start_ms)
      .map((moment) => ({
        label: `${moment.kind} · ${clock(moment.source.start_ms)} · ${moment.title}`,
        text: [
          moment.movedToward
            ? `You moved toward: ${moment.movedToward.text}`
            : "",
          moment.couldExplore
            ? `Could have explored: ${moment.couldExplore}`
            : "",
          moment.why ? `Why it mattered: ${moment.why.text}` : "",
        ]
          .filter(Boolean)
          .join(" "),
        evidence: [moment.source],
      })),
    model.skills.map((skill) => ({
      label: `${skill.label} · ${skill.state ?? "Not established"}`,
      text:
        skill.observation ??
        "This report does not establish a state for this skill.",
      evidence: skill.sources.slice(0, 2),
    })),
    [
      { label: "Current status", text: status },
      ...line("Prospect's position", deal.position),
      ...line(
        deal.blocker?.inferred ? "Possible blocker" : "Current blocker",
        deal.blocker,
      ),
      ...deal.prospectCommitments.flatMap((item) =>
        line("Prospect agreed to", item),
      ),
      ...deal.sellerCommitments.flatMap((item) => line("You agreed to", item)),
      ...line("Next event", deal.nextEvent),
      ...(deal.quality
        ? [{ label: "Commitment quality", text: deal.quality }]
        : []),
      ...(deal.unclear.length
        ? [
            {
              label: "Still needs to become clear",
              text: deal.unclear.join(" · "),
            },
          ]
        : []),
      ...(deal.action
        ? [
            {
              label: "Recommended next move",
              text: deal.action,
              inferred: true,
            },
          ]
        : []),
    ],
  ];
}

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
  const model = reportStoryModel(input.report, input.transcript ?? undefined);
  const pillars = storyEntries(model);
  REPORT_PILLARS.forEach((pillar, index) => {
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
    for (const entry of pillars[index]) {
      children.push(
        new Paragraph({
          children: [
            new TextRun({ text: entry.label, bold: true }),
            new TextRun({ text: entry.inferred ? " · Interpretation" : "" }),
          ],
          spacing: { before: 100, after: 40 },
          keepNext: true,
        }),
      );
      if (entry.text)
        children.push(
          new Paragraph({
            text: entry.text,
            spacing: { after: 60 },
            keepLines: true,
          }),
        );
      for (const evidence of entry.evidence ?? [])
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
    }
    if (model.missing[index].length)
      children.push(
        new Paragraph({
          text: "Not clear from this call.",
          spacing: { before: 80, after: 60 },
        }),
      );
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
