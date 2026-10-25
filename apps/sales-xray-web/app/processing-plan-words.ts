/**
 * Who processes a call, in plain words (owner, 26 Oct 2026: the full report's
 * approval repeated one paragraph three times and showed raw model ids). One
 * line per provider, naming what it does, and each privacy notice once. The
 * plan the person accepts is unchanged: this is only how it is shown.
 */

type Stage = Readonly<{
  stage: string;
  provider: string;
  privacy_notice: string;
}>;

/** What each stage does, as a person would say it. */
const STAGE_WORDS: Record<string, "Audio" | "Transcript and analysis"> = {
  C2: "Audio",
  C4: "Transcript and analysis",
  C5: "Transcript and analysis",
};

/** A provider's name, never its model id. */
export function providerName(provider: string): string {
  const id = provider.trim();
  if (/eleven/i.test(id)) return "ElevenLabs";
  if (/gemini|google|vertex/i.test(id)) return "Google Gemini";
  if (/openai|gpt/i.test(id)) return "OpenAI";
  if (/anthropic|claude/i.test(id)) return "Anthropic";
  const words = id.replace(/[-_]+/g, " ").trim();
  return words
    ? words[0].toUpperCase() + words.slice(1)
    : "An approved provider";
}

/** "Audio: ElevenLabs", "Transcript and analysis: Google Gemini", in plan order. */
export function providerLines(stages: readonly Stage[]): string[] {
  const byProvider = new Map<string, string[]>();
  for (const stage of stages) {
    const name = providerName(stage.provider);
    const work = STAGE_WORDS[stage.stage] ?? "Analysis";
    const jobs = byProvider.get(name) ?? [];
    if (!jobs.includes(work)) jobs.push(work);
    byProvider.set(name, jobs);
  }
  // One provider doing both reads "Audio, transcript and analysis".
  return [...byProvider].map(
    ([name, [first, ...rest]]) =>
      `${[first, ...rest.map((job) => job.toLowerCase())].join(", ")}: ${name}`,
  );
}

/** Each privacy notice once, in plan order. */
export function privacyNotices(stages: readonly Stage[]): string[] {
  return [
    ...new Set(stages.map((stage) => stage.privacy_notice.trim())),
  ].filter(Boolean);
}
