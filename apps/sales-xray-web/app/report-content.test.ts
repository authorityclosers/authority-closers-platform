// @vitest-environment node
import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { parseReportContent } from "./report-content";
import { parseJobResponse } from "./report-contract";
import { CALL_OUTCOMES } from "./report-story";
import { reportStoryModel } from "./report-story-model";
import { buildReportDocx } from "./report-docx";
import {
  contentFixture,
  contentReport,
  contentTranscript,
} from "./review-fixture/report/pillars/content-fixture";

describe("validated Report content", () => {
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
    const blob = await buildReportDocx({
      title: "Fictional contract",
      report: contentReport,
      transcript: contentTranscript,
    });
    const xml = execFileSync(
      "python3",
      [
        "-c",
        "import io,sys,zipfile; print(zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).read('word/document.xml').decode())",
      ],
      { input: Buffer.from(await blob.arrayBuffer()) },
    ).toString();
    for (const text of [
      model.picture.summary!.text,
      model.picture.strongest!.text,
      model.deal.nextEvent!.text,
      model.deal.sellerCommitments[0].text,
    ])
      expect(xml).toContain(text);
    expect(xml).toContain("Not clear from this call.");
    expect(xml).not.toContain("Coaching mission");
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
});
