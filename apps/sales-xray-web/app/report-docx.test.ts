// @vitest-environment node
import { execFileSync } from "node:child_process";
import { expect, it } from "vitest";
import { createReportDocx, reportDocxFilename } from "./report-docx";
import {
  syntheticEvidence,
  syntheticReport,
} from "./review-fixture/report/synthetic-report";

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
assert {'[Content_Types].xml', '_rels/.rels', 'word/document.xml', 'word/styles.xml', 'word/numbering.xml'} <= set(z.namelist())
for name in z.namelist():
 if name.endswith(('.xml', '.rels')): E.fromstring(z.read(name))
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
d = E.fromstring(z.read('word/document.xml'))
styles = E.fromstring(z.read('word/styles.xml'))
def attr(e, name): return e.get('{'+ns['w']+'}'+name)
def text(e): return ''.join(t.text or '' for t in e.findall('.//w:t', ns))
print(json.dumps({
 'text': text(d),
 'headings': [text(p) for p in d.findall('.//w:body/w:p', ns) if (s:=p.find('w:pPr/w:pStyle',ns)) is not None and attr(s,'val') in ('Title','Heading1','Heading2')],
 'chapters': [text(p) for p in d.findall('.//w:body/w:p',ns) if p.find('w:pPr/w:pageBreakBefore',ns) is not None],
 'tables': [[text(c) for c in t.findall('w:tr/w:tc',ns)] for t in d.findall('.//w:tbl',ns)],
 'unsplitRows': len(d.findall('.//w:trPr/w:cantSplit',ns)),
 'rows': len(d.findall('.//w:tr',ns)),
 'repeatedHeaders': len([h for h in d.findall('.//w:trPr/w:tblHeader',ns) if attr(h,'val') not in ('false','0','off')]),
 'page': {k: attr(d.find('.//w:pgSz',ns), k) for k in ('w','h')},
 'margin': {k: attr(d.find('.//w:pgMar',ns),k) for k in ('top','bottom','left','right')},
 'styles': [attr(s,'styleId') for s in styles.findall('w:style',ns)],
 'fonts': [attr(f,'ascii') for f in styles.findall('.//w:rFonts',ns)],
 'sizes': [attr(s,'val') for s in styles.findall('.//w:sz',ns)],
 'numbering': bool(d.findall('.//w:numPr',ns)),
 'header': text(E.fromstring(z.read('word/header1.xml'))),
 'footerFields': ''.join(E.fromstring(z.read('word/footer1.xml')).itertext()),
}))
`,
      ],
      { input: buffer, encoding: "utf8" },
    ),
  );

it("produces valid OOXML with the report, real styles, A4 chapters and protected tables", async () => {
  const evidence = Object.values(syntheticEvidence);
  const blob = await createReportDocx({
    title: "Fictional call <&> report",
    report: syntheticReport,
    transcript: {
      source_sha256: syntheticReport.source_sha256,
      revision: "fictional-r1",
      timebase_id: "fictional",
      duration_ms: 35000,
      segments: evidence.map((e) => ({
        id: e.segment_id,
        speaker_id: null,
        start_ms: e.start_ms,
        end_ms: e.end_ms,
        text: e.quote,
      })),
    },
  });
  expect(blob.type).toBe(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  );
  const xml = inspect(Buffer.from(await blob.arrayBuffer()));
  expect(xml.text).toContain(syntheticReport.summary);
  expect(xml.text).toContain(syntheticReport.verdict);
  evidence.forEach((e) => expect(xml.text).toContain(e.quote));
  expect(xml.text).toContain("Not scored");
  expect(xml.chapters).toEqual([
    "Overview",
    "Moments",
    "Analysis",
    "Coaching",
    "Transcript appendix",
  ]);
  expect(xml.headings).toMatchSnapshot();
  expect(xml.tables).toMatchSnapshot();
  expect(xml.styles).toMatchSnapshot();
  expect(xml.unsplitRows).toBe(xml.rows);
  expect(xml.repeatedHeaders).toBe(3);
  expect(xml.page).toEqual({ w: "11906", h: "16838" });
  expect(xml.margin).toEqual({
    top: "1074",
    bottom: "1074",
    left: "1074",
    right: "1074",
  });
  expect(xml.fonts).toContain("Calibri");
  expect(xml.sizes).toEqual(expect.arrayContaining(["21", "30", "24"]));
  expect(xml.numbering).toBe(true);
  expect(xml.header).toContain("Sales Xray · Fictional call <&> report");
  expect(xml.footerFields).toContain("PAGE");
  expect(xml.footerFields).toContain("NUMPAGES");
  expect(xml.text.indexOf(evidence[0].quote)).toBeLessThan(
    xml.text.lastIndexOf("Transcript appendix"),
  );
});

it("does not export a missing report, or make up a title or filename", async () => {
  await expect(createReportDocx({})).rejects.toThrow("document_report_missing");
  expect(reportDocxFilename("Fictional call")).toBe(
    "Fictional call – Sales Xray report.docx",
  );
  expect(reportDocxFilename("A/B: <call>\u0000")).toBe(
    "A B   call – Sales Xray report.docx",
  );
});
