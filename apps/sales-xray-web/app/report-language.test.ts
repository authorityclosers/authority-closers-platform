import { expect, it } from "vitest";
import { parseLanguageCapabilities } from "./report-language";
import { parseProcessingPlan } from "./call-studio";
import { plan, recordingId } from "../tests/acquisition-fixture";

it("preserves the exact absent-options shape for old entry and plan responses", () => {
  expect(parseLanguageCapabilities({})).toEqual({});
  expect(parseProcessingPlan(plan, recordingId)).not.toHaveProperty(
    "report_language",
  );
});
it.each(
  [
    {},
    { report_languages: ["en", "en"], report_language_default: "en" },
    { report_languages: ["en"], report_language_default: "mr-Deva+en" },
    { report_languages: ["xx"], report_language_default: "xx" },
  ].slice(1),
)("rejects invalid language capability projection %j", (input) =>
  expect(() => parseLanguageCapabilities(input)).toThrow(),
);
it.each(["en", "hi-Deva+en", "mr-Deva+en"])(
  "accepts %s only with a compatible frozen revision",
  (language) => {
    for (const revision of ["coaching-v4", "coaching-v5"]) {
      expect(
        parseProcessingPlan(
          {
            ...plan,
            report_language: language,
            coaching_prompt_revision: revision,
          },
          recordingId,
        ).report_language,
      ).toBe(language);
    }
    if (language !== "en")
      expect(() =>
        parseProcessingPlan(
          {
            ...plan,
            report_language: language,
            coaching_prompt_revision: "coaching-v3",
          },
          recordingId,
        ),
      ).toThrow();
  },
);
it("rejects partial or unknown plan language metadata", () => {
  expect(() =>
    parseProcessingPlan({ ...plan, report_language: "en" }, recordingId),
  ).toThrow();
  expect(() =>
    parseProcessingPlan(
      {
        ...plan,
        report_language: "en",
        coaching_prompt_revision: "coaching-v6",
      },
      recordingId,
    ),
  ).toThrow();
  expect(() =>
    parseProcessingPlan(
      {
        ...plan,
        report_language: "xx",
        coaching_prompt_revision: "coaching-v4",
      },
      recordingId,
    ),
  ).toThrow();
});
