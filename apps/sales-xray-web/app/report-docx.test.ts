// @vitest-environment node
import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import type { CallRecord } from "./call-record-contract";
import type { Transcript } from "./report-contract";
import {
  blockLabel,
  clock,
  createReportDocx,
  missedChances,
  moments,
  reportDocxFilename,
  talkSlices,
  voices,
} from "./report-docx";
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
 'cs': sorted({attr(f,'cs') for f in d.findall('.//w:rFonts',ns) if attr(f,'cs')}),
}))
`,
      ],
      { input: buffer, encoding: "utf8" },
    ),
  );

const segment = (
  id: string,
  speaker: string,
  start: number,
  end: number,
  text: string,
) => ({
  id,
  speaker_id: speaker,
  start_ms: start,
  end_ms: end,
  text,
});

const transcript: Transcript = {
  source_sha256: syntheticReport.source_sha256,
  revision: syntheticReport.transcript_revision,
  timebase_id: "fictional",
  duration_ms: 180000,
  segments: [
    segment("a1", "voice-b", 0, 30000, "Fictional buyer opens the call."),
    segment(
      "a2",
      "voice-a",
      31000,
      120000,
      "Fictional seller explains the plan?",
    ),
    segment("a3", "voice-b", 121000, 179000, "Fictional buyer declines."),
  ],
};

const callRecord: CallRecord = {
  version: "call-record/1",
  numbers: {
    duration_ms: 180000,
    overlaps: 2,
    speakers: [
      {
        speaker_id: "voice-a",
        talk_ms: 89000,
        talk_share: 0.6,
        questions: 4,
        longest_monologue_ms: 89000,
      },
      {
        speaker_id: "voice-b",
        talk_ms: 88000,
        talk_share: 0.4,
        questions: 1,
        longest_monologue_ms: 58000,
      },
    ],
  },
  facts: [
    {
      statement: "Fictional promise to send a brochure",
      evidence: [],
      tag: "promise",
    },
    {
      statement: "Fictional monthly budget mentioned",
      evidence: [],
      tag: "money",
    },
  ],
  tags: null,
  call_type: "first_meeting",
};

describe("report DOCX", () => {
  it("produces valid A4 OOXML with every section bookmarked and one page break", async () => {
    const blob = await createReportDocx({
      title: "Fictional call <&> report",
      report: syntheticReport,
      transcript,
      callRecord,
      speakerNames: { "voice-a": "Fictional seller" },
      repName: "Fictional seller",
    });
    const xml = inspect(Buffer.from(await blob.arrayBuffer()));
    expect(xml.page).toEqual({ w: "11906", h: "16838" });
    expect(xml.margin).toEqual({
      top: "850",
      bottom: "850",
      left: "850",
      right: "850",
    });
    expect(xml.bookmarks).toEqual([
      "overview",
      "coaching",
      "moments",
      "missed",
      "skills",
      "facts",
    ]);
    expect(xml.pageBreaks).toBe(1);
    expect(xml.fixedTables).toBe(xml.tables);
    expect(xml.text).toContain("Fictional call <&> report");
    expect(xml.text).toContain(syntheticReport.summary);
    for (const label of [
      "Keep doing",
      "Fix first",
      "Who spoke, and when",
      "Moments to replay",
      "Missed chances",
      "Skills checked",
      "Facts heard on the call",
    ])
      expect(xml.text.toUpperCase()).toContain(label.toUpperCase());
    expect(xml.text).toContain("Fictional seller");
    expect(xml.text).toContain("Fictional promise to send a brochure");
    expect(xml.text).toContain("Draft coaching");
    expect(xml.footer).toMatch(/PAGE/);
    expect(xml.cs).toEqual(["Nirmala UI"]);
  });

  it("still makes a complete document for an older report with no overview or numbers", async () => {
    const { overview: _overview, ...older } = syntheticReport;
    void _overview;
    const blob = await createReportDocx({
      title: "Older fictional call",
      report: { ...older, dimensions: [] },
    });
    const xml = inspect(Buffer.from(await blob.arrayBuffer()));
    expect(xml.bookmarks).toEqual([
      "overview",
      "coaching",
      "moments",
      "missed",
      "skills",
      "facts",
    ]);
    expect(xml.text.toUpperCase()).toContain("VERDICT");
    expect(xml.text).toContain("Skills were not checked for this call.");
    expect(xml.text).toContain("No facts were recorded for this call.");
    expect(xml.text).not.toContain("Who spoke, and when");
  });

  it("refuses to build without a report", async () => {
    await expect(createReportDocx({})).rejects.toThrow(
      "document_report_missing",
    );
  });
});

describe("report DOCX data", () => {
  it("formats recording times", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(61499)).toBe("1:01");
    expect(clock(3723000)).toBe("1:02:03");
  });

  it("names voices like the app and orders them by talk time", () => {
    const list = voices({
      title: "x",
      report: syntheticReport,
      transcript,
      callRecord,
    });
    expect(list.map((voice) => [voice.id, voice.name])).toEqual([
      ["voice-a", "Speaker 2"],
      ["voice-b", "Speaker 1"],
    ]);
    const fromTranscript = voices({
      title: "x",
      report: syntheticReport,
      transcript,
    });
    expect(fromTranscript[0]).toMatchObject({
      id: "voice-a",
      questions: 1,
      longestMs: 89000,
    });
  });

  it("splits the call into at most thirty blocks of a nameable length", () => {
    const { count, size, rows } = talkSlices(transcript, 180000, [
      "voice-a",
      "voice-b",
    ]);
    expect([count, blockLabel(size)]).toEqual([12, "15 s"]);
    expect(rows[0][5]).toBeCloseTo(1, 2);
    expect(rows[1][0]).toBeCloseTo(1, 2);
    const long = talkSlices(transcript, 2 * 3600000, ["voice-a"]);
    expect([long.count, blockLabel(long.size)]).toEqual([24, "5 min"]);
    const short = talkSlices(
      { ...transcript, segments: [segment("s", "voice-a", 30000, 35000, "x")] },
      35000,
      ["voice-a"],
    );
    // The last block is five seconds long and fully spoken.
    expect(short.count).toBe(3);
    expect(short.rows[0][2]).toBeCloseTo(1, 2);
  });

  it("numbers moments by time and keeps missed chances to three", () => {
    const list = moments(syntheticReport);
    expect(list.map((moment) => moment.number)).toEqual(
      list.map((_, i) => i + 1),
    );
    expect([...list].sort((a, b) => a.startMs - b.startMs)).toEqual(list);
    expect(missedChances(syntheticReport).length).toBeLessThanOrEqual(3);
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
