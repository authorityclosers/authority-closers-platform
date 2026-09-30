import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import fixture from "./review-fixture/report/call-record.json";
import { parseCallRecord } from "./call-record-contract";
import { CallRecordView } from "./call-record";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const callRecord = parseCallRecord(fixture);
let host: HTMLDivElement;
let root: Root;

async function render(record: typeof callRecord | null) {
  await act(async () => root.render(<CallRecordView callRecord={record} />));
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("CallRecordView", () => {
  it("renders no section when callRecord is null", async () => {
    await render(null);
    expect(host.querySelector('[aria-label="Call Record"]')).toBeNull();
    expect(host.textContent).not.toContain("Call details unavailable");
  });

  it("renders call numbers and quoted facts", async () => {
    await render(callRecord);
    expect(host.textContent).toContain("Total call duration: 22:00");
    expect(host.textContent).toContain("Who talked most: Buyer (60%)");
    expect(host.textContent).toContain(
      "Questions asked: Rep asked 14, Buyer asked 6",
    );
    expect(host.textContent).toContain("Longest monologue: Buyer (01:12)");
    expect(host.textContent).toContain("Times speakers talked at once: 5");
    expect(host.textContent).toContain(
      "Current billing system lacks automated reconciliation.",
    );
    expect(host.textContent).toContain(
      "Our current billing system does not handle reconciliation automatically.",
    );
    expect(host.textContent).toContain("02:25");
  });

  it("shows facts with empty tag metadata in Other", async () => {
    const emptyTags = {
      ...callRecord,
      tags: [],
      facts: [
        { ...callRecord.facts[0], tag: null },
        { ...callRecord.facts[1], tag: "" },
      ],
    };
    await render(emptyTags);
    expect(host.textContent).toContain("Other");
    expect(host.textContent).toContain(emptyTags.facts[0].statement);
    expect(host.textContent).toContain(emptyTags.facts[1].statement);
  });

  it("shows untagged facts when record tags are null", async () => {
    const nullTags = {
      ...callRecord,
      tags: null,
      facts: [{ ...callRecord.facts[0], tag: null }],
    };
    await render(nullTags);
    expect(host.textContent).toContain("Other");
    expect(host.textContent).toContain(nullTags.facts[0].statement);
  });

  it("shows facts with unknown tags in Other", async () => {
    const unknownTag = {
      ...callRecord,
      facts: [{ ...callRecord.facts[0], tag: "Unmapped category" }],
    };
    await render(unknownTag);
    expect(host.textContent).toContain("Other");
    expect(host.textContent).toContain(unknownTag.facts[0].statement);
    expect(host.textContent).not.toContain("Unmapped category");
  });

  it("keeps canonical, unknown, and untagged facts in a mixed record", async () => {
    const mixed = {
      ...callRecord,
      tags: [],
      facts: [
        { ...callRecord.facts[0], tag: "People" },
        { ...callRecord.facts[1], tag: "Unmapped category" },
        { ...callRecord.facts[2], tag: null },
      ],
    };
    await render(mixed);
    expect(host.textContent).toContain("People");
    expect(host.textContent).toContain("Other");
    for (const fact of mixed.facts) {
      expect(host.textContent).toContain(fact.statement);
    }
  });

  it("does not render facts without quoted evidence", async () => {
    const noQuote = {
      ...callRecord,
      facts: [
        ...callRecord.facts,
        {
          statement: "Invisible phantom statement",
          evidence: [],
          tag: "Business details",
        },
      ],
    };
    await render(noQuote);
    expect(host.textContent).not.toContain("Invisible phantom statement");
  });
});
