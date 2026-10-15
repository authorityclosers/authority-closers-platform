// @vitest-environment node
import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { parseReportContent } from "./report-content";
import { parseJobResponse } from "./report-contract";
import { CALL_OUTCOMES } from "./report-story";
import { reportStoryModel } from "./report-story-model";
import { createReportDocx } from "./report-docx";
import { docItemText, reportDocumentModel } from "./report-document-model";
import { BIG_PICTURE, COMMON } from "./report-copy";
import {
  contentFixture,
  contentReport,
  contentTranscript,
} from "./review-fixture/report/pillars/content-fixture";

describe("validated Report content", () => {
  it.each([
    { status: "Won" as const, note: "Fictional human result." },
    { status: "Won" as const },
    { status: "Lost" as const, note: "Fictional human result." },
    { status: "Lost" as const },
  ])(
    "preserves the recorded result in Report, Document and Word: %j",
    async (recorded) => {
      const report = {
        ...contentReport,
        report_content: { ...contentFixture, position: contentFixture.outcome },
      };
      const people = { recorded };
      const model = reportStoryModel(report, contentTranscript, people);
      const expected = {
        status: recorded.status,
        origin: "person",
        detail: recorded.note ? { text: recorded.note, sources: [] } : null,
      };
      expect(model.picture.outcome).toEqual(expected);
      expect(model.deal.outcome).toEqual(expected);
      expect(model.deal.position).toEqual({
        text: contentFixture.outcome!.text,
        sources: contentFixture.outcome!.evidence,
      });
      const noPosition = reportStoryModel(
        {
          ...report,
          report_content: { ...report.report_content, position: null },
        },
        contentTranscript,
        people,
      );
      expect(noPosition.deal.position).toEqual(model.deal.position);
      const data = { report, transcript: contentTranscript };
      const doc = reportDocumentModel(data, people);
      const outcomeItems = doc.sections[0].parts[0].items;
      expect(outcomeItems[0]).toMatchObject({
        type: "status",
        status: recorded.status,
        origin: BIG_PICTURE.outcomeByPerson,
      });
      const outcomeText = outcomeItems.map(docItemText).join(" ");
      if (recorded.note) expect(outcomeText).toContain(recorded.note);
      expect(outcomeText).not.toContain(contentFixture.outcome!.text);
      const blob = await createReportDocx(data, people);
      const wordText = execFileSync(
        "python3",
        [
          "-c",
          "import io,sys,zipfile,xml.etree.ElementTree as ET; root=ET.fromstring(zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).read('word/document.xml')); print(' '.join(n.text or '' for n in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')))",
        ],
        { input: Buffer.from(await blob.arrayBuffer()) },
      ).toString();
      expect(wordText).toContain(recorded.status);
      expect(wordText).toContain(BIG_PICTURE.outcomeByPerson);
      if (recorded.note) expect(wordText).toContain(recorded.note);
      expect(wordText).toContain(contentFixture.outcome!.text);
    },
  );

  it.each(CALL_OUTCOMES)(
    "retains explicit %s without setting saved deal state",
    (status) => {
      const content = parseReportContent(
        { ...contentFixture, outcome: { ...contentFixture.outcome, status } },
        contentTranscript,
      );
      expect(content.outcome?.status).toBe(status);
      const model = reportStoryModel(
        { ...contentReport, report_content: content },
        contentTranscript,
      );
      expect(model.picture.outcome.status).toBe(
        ["Won", "Lost"].includes(status) ? null : status,
      );
    },
  );
  it.each([
    "actor",
    "quote",
    "time",
    "date",
    "agreement",
    "summary",
    "order",
    "extra",
  ])("rejects %s errors", (fault) => {
    const c = structuredClone(contentFixture);
    if (fault === "actor") c.strongest!.actor_id = "buyer";
    if (fault === "quote") c.strongest!.evidence[0].quote = "Can we";
    if (fault === "time") c.strongest!.evidence[0].start_ms++;
    if (fault === "date") c.next_event!.date_text = "Tuesday";
    if (fault === "agreement")
      c.next_event!.agreement_evidence = [
        ...c.seller_commitments[0].evidence,
        ...c.strongest!.evidence,
      ];
    if (fault === "summary") c.summary_sentences.pop();
    if (fault === "order") c.phases.reverse();
    if (fault === "extra")
      Object.assign(c.worked[0], {
        replacement_behavior: "Ask better questions.",
      });
    expect(() => parseReportContent(c, contentTranscript)).toThrow(
      "report_content_invalid",
    );
  });
  it("parses through the actual report transport and uses the explicit contract in all six pillars", () => {
    const parsed = parseJobResponse(
      { id: "fictional-run", state: "completed", report: contentReport },
      {
        sourceSha256: contentTranscript.source_sha256,
        durationMs: 6000,
        transcript: contentTranscript,
      },
    );
    expect(parsed.report!.report_content).toEqual(contentFixture);
    const model = reportStoryModel(parsed.report!, contentTranscript);
    expect(model.flow.phases).toHaveLength(3);
    expect(model.picture.strongest?.sources[0].quote).toBe(
      contentTranscript.segments[4].text,
    );
    expect(model.deal.nextEvent?.text).toContain("Friday · 4 PM");
    expect(model.deal.quality).toBe("Clear");
    expect(model.skills[1].state).toBe("Not Applicable");
    expect(model.moments).toHaveLength(1);
    expect(model.didnt).toEqual([]);
    expect(model.deal.coachingMission).toBeNull();
  });
  it("Word contains the same supported facts and sources as the browser model", async () => {
    const model = reportStoryModel(contentReport, contentTranscript);
    const blob = await createReportDocx({
      title: "Fictional contract",
      report: contentReport,
      transcript: contentTranscript,
    });
    const documentText = execFileSync(
      "python3",
      [
        "-c",
        "import io,sys,zipfile,xml.etree.ElementTree as ET; root=ET.fromstring(zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).read('word/document.xml')); print(' '.join(n.text or '' for n in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')))",
      ],
      { input: Buffer.from(await blob.arrayBuffer()) },
    ).toString();
    for (const text of [
      model.picture.summary!.text,
      model.picture.strongest!.text,
      model.deal.nextEvent!.text,
      model.deal.sellerCommitments[0].text,
    ])
      expect(documentText).toContain(text);
    expect(documentText).toContain(COMMON.gapsLead);
    expect(documentText).not.toContain("Coaching mission");
  });
  it("does not repeat the outcome as position, infer legacy states, or promote prospect tasks", () => {
    const c = { ...contentFixture, position: contentFixture.outcome };
    expect(
      reportStoryModel({ ...contentReport, report_content: c }).deal.position,
    ).toBeNull();
    const legacy = {
      ...contentReport,
      report_content: undefined,
      dimensions: contentReport.dimensions.map((d) => ({
        ...d,
        call_state: undefined,
      })),
    };
    expect(reportStoryModel(legacy).skills[0].state).toBeNull();
  });
  it("retains validated candidate facts when an older pillar projection is also present", () => {
    const report = {
      ...contentReport,
      pillars: {
        version: "report-pillars/1" as const,
        summary: "An older projection of this call.",
        outcome: {
          status: "Deferred" as const,
          line: "Older projection of the outcome.",
          evidence: contentFixture.outcome!.evidence,
        },
      },
    };
    const model = reportStoryModel(report, contentTranscript);
    expect(model.picture.summary?.text).toBe(contentReport.summary);
    expect(model.deal.nextEvent?.text).toContain("Friday · 4 PM");
    expect(model.deal.coachingMission).toBeNull();
    const observed = {
      status: "Meeting Booked",
      origin: "call",
      detail: {
        text: contentFixture.outcome!.text,
        sources: contentFixture.outcome!.evidence,
      },
    };
    expect(model.picture.outcome).toEqual(observed);
    expect(model.deal.outcome).toEqual(observed);
    for (const status of ["Won", "Lost"] as const) {
      const recorded = { status, note: "Fictional human result." };
      const overridden = reportStoryModel(report, contentTranscript, {
        recorded,
      });
      const expected = {
        status,
        origin: "person",
        detail: { text: recorded.note, sources: [] },
      };
      expect(overridden.picture.outcome).toEqual(expected);
      expect(overridden.deal.outcome).toEqual(expected);
      expect(overridden.deal.nextEvent?.text).toContain("Friday · 4 PM");
    }
  });
});
