import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "../tests/fixtures/call-record.json";
import { parseCallRecord } from "./call-record-contract";
import { CallRecordView } from "./call-record";

describe("CallRecordView", () => {
  const callRecord = parseCallRecord(fixture);

  it("renders 'Call details unavailable' when callRecord is null", () => {
    render(<CallRecordView callRecord={null} />);
    expect(screen.getByTestId("call-details-unavailable")).toHaveTextContent(
      "Call details unavailable",
    );
  });

  it("renders the numbers card with duration, talk share, questions, monologue, overlaps, and plain labels", () => {
    render(<CallRecordView callRecord={callRecord} />);
    // Duration
    expect(screen.getByText("Total call duration: 22:00")).toBeInTheDocument();

    // Plain label for talk share
    expect(
      screen.getByText(/Who talked most: Buyer \(60%\)/),
    ).toBeInTheDocument();

    // Questions
    expect(
      screen.getByText(/Questions asked: Rep asked 14, Buyer asked 6/),
    ).toBeInTheDocument();

    // Longest monologue
    expect(
      screen.getByText(/Longest monologue: Buyer \(01:12\)/),
    ).toBeInTheDocument();

    // Overlaps
    expect(
      screen.getByText("Times speakers talked at once: 5"),
    ).toBeInTheDocument();
  });

  it("renders facts with statement, quote, m:ss time, and Play button", () => {
    render(<CallRecordView callRecord={callRecord} />);
    expect(
      screen.getByText("Current billing system lacks automated reconciliation."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Our current billing system does not handle reconciliation automatically.",
      ),
    ).toBeInTheDocument();
    // 145000 ms = 02:25
    expect(screen.getByText("02:25")).toBeInTheDocument();
  });

  it("groups facts into tag cards when tags are present, without rendering empty tag cards", () => {
    render(<CallRecordView callRecord={callRecord} />);
    expect(screen.getByRole("heading", { name: "People" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Business details" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Next steps and commitments" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Concerns" }),
    ).toBeInTheDocument();
  });

  it("renders a single flat facts card when tags is null", () => {
    const withoutTags = {
      ...callRecord,
      tags: null,
    };
    render(<CallRecordView callRecord={withoutTags} />);
    expect(screen.getByRole("heading", { name: "Facts" })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "People" }),
    ).not.toBeInTheDocument();
  });

  it("never renders facts that lack quotes", () => {
    const withEmptyQuote = {
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
    render(<CallRecordView callRecord={withEmptyQuote} />);
    expect(
      screen.queryByText("Invisible phantom statement"),
    ).not.toBeInTheDocument();
  });
});
