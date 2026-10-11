/** Opt-in offline check of the Document view on retained real reports; private inputs stay outside Git and logs. */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { parseJobResponse, parseTranscript } from "./report-contract";
import { ReportDocumentSheet } from "./report-document";
import { docItemText, reportDocumentModel } from "./report-document-model";

const corpus = process.env.AC_REPORT_CORPUS_DIR;

/** Analyst words Dipak's voice avoids (the same list H's VOICE block bans). */
const ANALYST =
  /\b(conducted|effective(ly)?|crisp|leverag\w*|utili[sz]\w*|facilitat\w*|alignment|mechanics|robust|optimi[sz]\w*|ensure[sd]?|articulat\w*|synerg\w*|consultative|interaction|rapport-building|de-escalat\w*)\b/gi;

it.skipIf(!corpus)(
  "builds and renders the Document for every retained real report, and counts analyst words",
  () => {
    let checked = 0,
      missing = 0,
      failures = 0,
      reportsWithAnalystWords = 0,
      analystWords = 0;
    const byWord: Record<string, number> = {};
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
            report: JSON.parse(readFileSync(join(baseline, "c5.json"), "utf8"))
              .payload,
          },
          {
            sourceSha256: transcript.source_sha256,
            durationMs: transcript.duration_ms,
            transcript,
          },
        );
        const doc = reportDocumentModel({ report: job.report!, transcript });
        const html = renderToStaticMarkup(
          createElement(ReportDocumentSheet, { doc, id: "corpus" }),
        );
        const headings = (html.match(/<h3\b/g) ?? []).length;
        if (doc.sections.length !== 6 || headings !== 6) failures++;
        if (/\b(undefined|null|NaN)\b|\[object Object\]/.test(html)) failures++;
        // Only the analysis' own sentences (fixed labels are checked elsewhere).
        const words = doc.sections
          .flatMap((s) => s.parts.flatMap((p) => p.items.map(docItemText)))
          .join("\n")
          .match(ANALYST);
        if (words?.length) {
          reportsWithAnalystWords++;
          analystWords += words.length;
          for (const word of words) {
            const key = word.toLowerCase();
            byWord[key] = (byWord[key] ?? 0) + 1;
          }
        }
        checked++;
      } catch {
        failures++;
      }
    }
    // Counts only: no customer words, paths or model output.
    console.info(
      JSON.stringify({
        checked,
        missing,
        failures,
        reportsWithAnalystWords,
        analystWords,
        byWord,
        provider_calls: 0,
      }),
    );
    expect(checked).toBeGreaterThan(0);
    expect(failures).toBe(0);
  },
  120000,
);
