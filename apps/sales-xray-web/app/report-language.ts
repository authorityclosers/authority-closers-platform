import { ReportContractError } from "./report-contract";

export const reportLanguages = ["en", "hi-Deva+en", "mr-Deva+en"] as const;
export type ReportLanguage = (typeof reportLanguages)[number];
export const reportLanguageLabels: Record<ReportLanguage, string> = {
  en: "English",
  "hi-Deva+en": "Hindi + English",
  "mr-Deva+en": "Marathi + English",
};
export function parseReportLanguage(value: unknown): ReportLanguage {
  if (
    typeof value !== "string" ||
    !reportLanguages.includes(value as ReportLanguage)
  )
    throw new ReportContractError("report_language_invalid");
  return value as ReportLanguage;
}
export function parseLanguageCapabilities(entry: Record<string, unknown>): {
  report_languages?: ReportLanguage[];
  report_language_default?: ReportLanguage;
} {
  if (
    entry.report_languages === undefined &&
    entry.report_language_default === undefined
  )
    return {};
  if (
    !Array.isArray(entry.report_languages) ||
    !entry.report_languages.length ||
    entry.report_languages.length > reportLanguages.length
  )
    throw new ReportContractError("report_languages_invalid");
  const supported = entry.report_languages.map(parseReportLanguage);
  const selected = parseReportLanguage(entry.report_language_default);
  if (
    new Set(supported).size !== supported.length ||
    !supported.includes(selected)
  )
    throw new ReportContractError("report_languages_invalid");
  return { report_languages: supported, report_language_default: selected };
}
