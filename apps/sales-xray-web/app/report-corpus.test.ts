/** Opt-in offline verification; private inputs stay outside Git and test logs. */
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { parseJobResponse, parseTranscript } from "./report-contract";
import { reportPillars } from "./report-pillars";
import { callCoachingFocus, ReportCallCoaching } from "./report-call-coaching";

const corpus = process.env.AC_REPORT_CORPUS_DIR;
it.skipIf(!corpus)(
  "opens retained C5 reports with six pillars, eight skills and call Coaching offline",
  () => {
    let checked = 0,
      missing = 0,
      failures = 0,
      coachingViews = 0,
      supportedFocus = 0;
    for (const folder of readdirSync(join(corpus!, "calls"))) {
      const baseline = join(corpus!, "calls", folder, "baseline");
      if (!existsSync(join(baseline, "c5.json"))) {
        missing++;
        continue;
      }
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
      }
    }
    // Counts only: no customer words, source paths, or model output.
    const receipt = JSON.stringify({
      checked,
      missing,
      coachingViews,
      supportedFocus,
      failures,
      provider_calls: 0,
    });
    console.info(receipt);
    expect(checked).toBeGreaterThan(0);
    expect(failures).toBe(0);
  },
);
