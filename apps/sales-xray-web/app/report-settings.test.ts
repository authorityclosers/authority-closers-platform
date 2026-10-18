import { describe, expect, it } from "vitest";

import {
  VERSION_1,
  applyReportSettings,
  parseReportSettings,
} from "./report-settings";

const panels = {
  story: [{ id: "overview" }, { id: "analysis" }, { id: "outcome" }],
  prospect: [{ id: "prospect-information" }],
  coaching: [{ id: "call-coaching" }],
};

describe("report settings in the app", () => {
  it("is version 1 (everything shown) for an older server or a broken answer", () => {
    expect(parseReportSettings({})).toEqual(VERSION_1);
    expect(parseReportSettings(null)).toEqual(VERSION_1);
    expect(applyReportSettings(panels, VERSION_1)).toEqual(panels);
  });

  it("hides the parts and tabs a version turns off", () => {
    const settings = parseReportSettings({
      version: { number: 3, label: "Compact" },
      source: "organisation",
      settings: {
        report: { parts: { overview: true, analysis: false, outcome: true } },
        prospect: { enabled: false },
        coaching: { enabled: true },
      },
    });
    expect(settings.version).toBe(3);
    expect(applyReportSettings(panels, settings)).toEqual({
      story: [{ id: "overview" }, { id: "outcome" }],
      prospect: [],
      coaching: [{ id: "call-coaching" }],
    });
  });

  it("never shows an empty Report", () => {
    const settings = parseReportSettings({
      settings: {
        report: { parts: { overview: false, analysis: false, outcome: false } },
      },
    });
    expect(applyReportSettings(panels, settings).story).toEqual(panels.story);
  });
});
