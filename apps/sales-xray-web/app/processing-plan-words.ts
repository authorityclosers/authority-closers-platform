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

/** "Audio, transcript and analysis: Google Gemini", in plan order. */
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

/** The providers a notice can name, as providerName names them. */
const NAMED: ReadonlyArray<readonly [RegExp, string]> = [
  [/elevenlabs/i, "ElevenLabs"],
  [/\b(?:gemini|google)\b/i, "Google Gemini"],
  [/\bopenai\b/i, "OpenAI"],
  [/\b(?:anthropic|claude)\b/i, "Anthropic"],
];

/**
 * Each privacy notice once, in plan order, never one that names a provider no
 * stage of this plan uses (26 Oct 2026: one-pass plans carried a sealed notice
 * sending the audio to ElevenLabs while Google Gemini transcribes it). The
 * provider lines above always say who processes the call.
 */
export function privacyNotices(stages: readonly Stage[]): string[] {
  const used = new Set(stages.map((stage) => providerName(stage.provider)));
  return [...new Set(stages.map((stage) => stage.privacy_notice.trim()))]
    .filter(Boolean)
    .filter((notice) =>
      NAMED.every(([named, name]) => !named.test(notice) || used.has(name)),
    );
}
