/** Opt-in offline verification; private inputs stay outside Git and test logs. */
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  parseAcquisitionReport,
  parseJobResponse,
  parseTranscript,
} from "./report-contract";
import { reportPillars } from "./report-pillars";
import { createReportDocx } from "./report-docx";
import { callCoachingFocus, ReportCallCoaching } from "./report-call-coaching";

const corpus = process.env.AC_REPORT_CORPUS_DIR;
const repository = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const recordingId = "11111111-1111-4111-8111-111111111111";
const submissionId = "22222222-2222-4222-8222-222222222222";
// These subprocesses receive private data only on stdin and keep it in memory.
// Only a fixed unavailable flag or projection is returned; exceptions never
// print model inputs. This is a projector check, not an ownership/read proof.
function projectedReports(report: unknown): unknown[] {
  const result = JSON.parse(
    execFileSync(
      join(repository, ".venv/bin/python"),
      [
        "-c",
        `
import json, sys
from uuid import UUID
from ac_platform.conversation_intelligence.reports import ReportDraft
from ac_platform.conversation_intelligence.report_access import (
    ReportAccess, ReportSourceBinding, project_bound_report,
)
try:
    report = ReportDraft.model_validate(json.load(sys.stdin))
    source = ReportSourceBinding(
        UUID('${recordingId}'), UUID('33333333-3333-4333-8333-333333333333'),
        report.source_sha256, report.transcript_revision,
    )
    views = [project_bound_report(report, access=access, source=source)
             for access in (ReportAccess.ACCOUNT, ReportAccess.GUEST)]
    json.dump(views, sys.stdout)
except Exception:
    sys.stdout.write('[]')
`,
      ],
      {
        input: JSON.stringify(report),
        encoding: "utf8",
        env: {
          ...process.env,
          PYTHONPATH: join(repository, "packages/python"),
        },
        maxBuffer: 4 * 1024 * 1024,
        timeout: 15000,
        stdio: ["pipe", "pipe", "pipe"],
      },
    ),
  );
  return Array.isArray(result) ? result : [];
}

function validDocument(bytes: ArrayBuffer): boolean {
  // Validate every XML part and the six bookmarks; never return document text.
  return (
    execFileSync(
      "python3",
      [
        "-c",
        `
import io, sys, zipfile, xml.etree.ElementTree as E
try:
    z = zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read()))
    assert z.testzip() is None
    assert {'[Content_Types].xml', '_rels/.rels', 'word/document.xml'} <= set(z.namelist())
    for name in z.namelist():
        if name.endswith(('.xml', '.rels')): E.fromstring(z.read(name))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    document = E.fromstring(z.read('word/document.xml'))
    bookmarks = [b.get('{'+ns['w']+'}name') for b in document.findall('.//w:bookmarkStart', ns)]
    assert bookmarks == ['overview', 'coaching', 'moments', 'missed', 'skills', 'facts']
    sys.stdout.write('ok')
except Exception:
    sys.stdout.write('unavailable')
`,
      ],
      { input: Buffer.from(bytes), encoding: "utf8", timeout: 5000 },
    ) === "ok"
  );
}
it.skipIf(!corpus)(
  "opens retained C5 account/guest projections, six pillars, eight skills, Word and call Coaching offline",
  async () => {
    let checked = 0,
      missing = 0,
      failures = 0,
      coachingViews = 0,
      supportedFocus = 0,
      accountProjections = 0,
      guestProjections = 0,
      documents = 0;
    const failureStages: Record<string, number> = {};
    for (const folder of readdirSync(join(corpus!, "calls"))) {
      const baseline = join(corpus!, "calls", folder, "baseline");
      if (!existsSync(join(baseline, "c5.json"))) {
        missing++;
        continue;
      }
      let stage = "stored_source";
      try {
        const native = JSON.parse(
          readFileSync(join(baseline, "c2.json"), "utf8"),
        ).payload;
        const report = JSON.parse(
          readFileSync(join(baseline, "c5.json"), "utf8"),
        ).payload;
        const transcript = parseTranscript(
          {
            source_sha256: native.source_sha256,
            revision: native.revision,
            timebase_id: native.timebase_id,
            duration_ms: native.duration_ms,
            segments: native.segments,
          },
          native.source_sha256,
        );
        stage = "stored_report";
        const job = parseJobResponse(
          {
            id: "offline-corpus",
            state: "completed",
            message: "Stored analysis",
            report,
          },
          {
            sourceSha256: transcript.source_sha256,
            durationMs: transcript.duration_ms,
            transcript,
          },
        );
        const pillars = reportPillars(job.report!, transcript.duration_ms);
        if (pillars.length !== 6 || pillars[4].entries.length !== 8) failures++;
        stage = "backend_projection";
        const projections = projectedReports(report);
        if (projections.length !== 2) failures++;
        for (const [index, projection] of projections.entries()) {
          stage = "projection_codec";
          const view = parseAcquisitionReport(
            { ...(projection as object), submission_id: submissionId },
            { recordingId, submissionId },
            transcript,
          );
          if (view.claimed !== (index === 0)) failures++;
          if (view.claimed) accountProjections++;
          else guestProjections++;
          const data = { report: view.report, transcript };
          stage = "word_export";
          const document = await createReportDocx(data);
          if (!validDocument(await document.arrayBuffer())) failures++;
          else documents++;
        }
        stage = "call_coaching";
        const focus = callCoachingFocus(job.report!);
        if (focus) {
          if (!focus.finding.evidence.length) failures++;
          supportedFocus++;
        }
        const html = renderToStaticMarkup(
          createElement(ReportCallCoaching, {
            data: { report: job.report, transcript },
          }),
        );
        if (!html.includes("data-call-coaching")) failures++;
        else coachingViews++;
        checked++;
      } catch {
        failures++;
        failureStages[stage] = (failureStages[stage] ?? 0) + 1;
      }
    }
    // Counts only: no customer words, source paths, or model output.
    const receipt = JSON.stringify({
      checked,
      missing,
      coachingViews,
      supportedFocus,
      accountProjections,
      guestProjections,
      documents,
      failureStages,
      failures,
      provider_calls: 0,
    });
    console.info(receipt);
    expect(checked).toBeGreaterThan(0);
    expect(failures).toBe(0);
  },
  120000,
);
