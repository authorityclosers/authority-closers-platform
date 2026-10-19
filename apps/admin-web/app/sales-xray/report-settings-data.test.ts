import { describe, expect, it } from "vitest";

import {
  describeChange,
  describeEvent,
  normalizeReportSettings,
  valueAt,
  withValue,
} from "./report-settings-data";

describe("report settings data", () => {
  it("never crashes on an empty or broken body", () => {
    const empty = normalizeReportSettings({});
    expect(empty.versions).toEqual([]);
    expect(empty.generalVersionNumber).toBeNull();
    expect(normalizeReportSettings(null).history).toEqual([]);
  });

  it("reads and edits dotted settings without touching the original", () => {
    const settings = { report: { parts: { outcome: true }, style: "guided" } };
    const next = withValue(settings, "report.parts.outcome", false);
    expect(valueAt(next, "report.parts.outcome")).toBe(false);
    expect(valueAt(settings, "report.parts.outcome")).toBe(true);
    expect(valueAt(next, "report.style")).toBe("guided");
    expect(valueAt(next, "coaching.tone")).toBeUndefined();
  });

  it("says changes and history in words", () => {
    const data = normalizeReportSettings({
      parameters: [
        {
          key: "report.style",
          surface: "report",
          label: "Report style",
          kind: "choice",
          choices: [
            { value: "guided", label: "Guided" },
            { value: "compact", label: "Compact" },
          ],
          in_app: false,
        },
      ],
      history: [
        {
          id: "1",
          kind: "assigned",
          scope: "organisation",
          organisation: "Wise Life",
          version_number: 3,
          previous_version_number: null,
          created_at: "2026-10-19T06:00:00Z",
        },
        {
          id: "2",
          kind: "version_created",
          scope: "version",
          version_number: 3,
          previous_version_number: 2,
        },
      ],
    });
    expect(
      describeChange(
        { key: "report.style", from: "guided", to: "compact" },
        data.parameters,
      ),
    ).toBe("Report · Report style: Guided → Compact");
    expect(
      describeChange({ key: "x.y", from: true, to: false }, data.parameters),
    ).toBe("x.y: on → off");
    expect(describeEvent(data.history[0]!)).toBe(
      "Wise Life: its default → version 3",
    );
    expect(describeEvent(data.history[1]!)).toBe(
      "Version 3 created from version 2",
    );
  });
});
