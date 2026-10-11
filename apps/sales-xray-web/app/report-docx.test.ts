// @vitest-environment node
import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import type { SalesReport, Transcript } from "./report-contract";
import { clock, createReportDocx, reportDocxFilename } from "./report-docx";
import { REPORT_PILLARS } from "./report-pillars";
import {
  AMIT_SPEAKERS,
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";
import { syntheticReport } from "./review-fixture/report/synthetic-report";

// Validate ZIP checksums and parse every OOXML part, rather than checking only a magic header.
const inspect = (buffer: Buffer) =>
  JSON.parse(
    execFileSync(
      "python3",
      [
        "-c",
        `
import io, json, sys, zipfile, xml.etree.ElementTree as E
z = zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read()))
assert z.testzip() is None
assert {'[Content_Types].xml', '_rels/.rels', 'word/document.xml', 'word/styles.xml'} <= set(z.namelist())
for name in z.namelist():
 if name.endswith(('.xml', '.rels')): E.fromstring(z.read(name))
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
d = E.fromstring(z.read('word/document.xml'))
def attr(e, name): return e.get('{'+ns['w']+'}'+name)
def text(e): return ''.join(t.text or '' for t in e.findall('.//w:t', ns))
footer = [n for n in z.namelist() if n.startswith('word/footer')]
print(json.dumps({
 'text': text(d),
 'bookmarks': [attr(b,'name') for b in d.findall('.//w:bookmarkStart',ns)],
 'pageBreaks': len(d.findall('.//w:pPr/w:pageBreakBefore',ns)),
 'page': {k: attr(d.find('.//w:pgSz',ns), k) for k in ('w','h')},
 'margin': {k: attr(d.find('.//w:pgMar',ns),k) for k in ('top','bottom','left','right')},
 'fixedTables': len(d.findall('.//w:tblLayout',ns)),
 'tables': len(d.findall('.//w:tbl',ns)),
 'footer': ''.join(E.fromstring(z.read(footer[0])).itertext()) if footer else '',
 'cs': sorted({attr(f,'cs') for tree in (d, E.fromstring(z.read('word/styles.xml'))) for f in tree.findall('.//w:rFonts',ns) if attr(f,'cs')}),
}))
`,
      ],
      { input: buffer, encoding: "utf8" },
    ),
  );

const bytes = async (blob: Blob) => Buffer.from(await blob.arrayBuffer());

const amit = () =>
  createReportDocx(
    {
      title: "Amit Sharma · discovery call",
      report: amitReport as SalesReport,
      transcript: amitTranscript as Transcript,
    },
    {
      roles: AMIT_SPEAKERS,
      speakerName: (id) =>
        id === AMIT_SPEAKERS.prospect ? "Amit Sharma" : "Arjun",
    },
  );

describe("report Word file", () => {
  it("is valid A4 OOXML with Dipak's six headings in order and stable bookmarks", async () => {
    const doc = inspect(await bytes(await amit()));
    expect(doc.page).toEqual({ w: "11906", h: "16838" });
    expect(doc.bookmarks).toEqual(REPORT_PILLARS.map((pillar) => pillar.id));
    const order = [
      "1. The Big Picture",
      "1.1 Call Outcome",
      "1.4 Strongest Part",
      "2. How the Call Played Out",
      "2.1 Call Metrics",
      "3. What Worked — & What Didn't",
      "4. Moments That Mattered",
      "5. Your Skills on This Call",
      "6. Where the Deal Stands",
      "6.1 Current Status",
    ].map((heading) => doc.text.indexOf(heading));
    expect(order.every((at: number) => at >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(doc.text).toContain("Amit Sharma agreed to:");
    expect(doc.text).toContain("Call Outcome");
    expect(doc.tables).toBeGreaterThanOrEqual(2);
    expect(doc.fixedTables).toBe(doc.tables);
    expect(doc.cs).toContain("Nirmala UI");
    expect(doc.footer).toContain("Times are from the recording");
    expect(doc.text).not.toMatch(/undefined|null|NaN|\[object Object\]/);
  });

  it("still makes a complete document for an older report", async () => {
    const doc = inspect(
      await bytes(
        await createReportDocx({ report: syntheticReport as SalesReport }),
      ),
    );
    expect(doc.bookmarks).toEqual(REPORT_PILLARS.map((pillar) => pillar.id));
    expect(doc.text).toContain("Sales call");
    expect(doc.text).toContain("This report doesn't cover:");
  });

  it("an observed skill without a note keeps its row: state and times", async () => {
    const report = structuredClone(amitReport) as SalesReport;
    for (const d of report.dimensions) d.observation = "";
    const doc = inspect(
      await bytes(
        await createReportDocx(
          { report, transcript: amitTranscript as Transcript },
          { roles: AMIT_SPEAKERS },
        ),
      ),
    );
    expect(doc.text).toContain("Human Connection & TrustStrongly Demonstrated");
    expect(doc.text).not.toContain("This report doesn't cover this skill.");
  });

  it("refuses to build without a report", async () => {
    await expect(createReportDocx({ title: "No report" })).rejects.toThrow(
      "document_report_missing",
    );
  });
});

describe("report Word file helpers", () => {
  it("formats recording times", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(65_400)).toBe("1:05");
    expect(clock(3_725_000)).toBe("1:02:05");
  });

  it("makes a safe file name", () => {
    expect(reportDocxFilename('A/B: "call"?')).toBe(
      "A B   call – Sales Xray report.docx",
    );
    expect(reportDocxFilename("  ")).toBe(
      "Sales Xray call – Sales Xray report.docx",
    );
  });
});
