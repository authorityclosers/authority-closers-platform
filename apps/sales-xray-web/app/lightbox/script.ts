import type { ReportLanguage } from "../report-language";

// Devanagari, Devanagari Extended and Vedic Extensions.
const DEVANAGARI = /[ऀ-ॿ꣠-ꣿ᳐-᳿]/;

export type ScriptAttributes = Readonly<{
  lang?: string;
  "data-script"?: "deva";
}>;

export function containsDevanagari(text: string): boolean {
  return DEVANAGARI.test(text);
}

/**
 * Source quotes and transcript rows. The requested report language is not proof
 * of the spoken language, so Devanagari gets an unknown-language script tag and
 * Latin text inherits the page language.
 */
export function sourceTextAttributes(text: string): ScriptAttributes {
  return containsDevanagari(text)
    ? { lang: "und-Deva", "data-script": "deva" }
    : {};
}

const proseLanguage: Record<ReportLanguage, string> = {
  en: "en",
  "hi-Deva+en": "hi",
  "mr-Deva+en": "mr",
};

/** Generated coaching prose may use the language bound to its report plan. */
export function reportProseAttributes(
  text: string,
  language: ReportLanguage | null | undefined,
): ScriptAttributes {
  return {
    ...(language ? { lang: proseLanguage[language] } : {}),
    ...(containsDevanagari(text) ? { "data-script": "deva" as const } : {}),
  };
}
