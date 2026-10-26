import { expect, it } from "vitest";

import {
  privacyNotices,
  providerLines,
  providerName,
} from "./processing-plan-words";

const NOTICE =
  "An approved provider transcribes the call and prepares its report.";

it("names providers, never their model ids", () => {
  expect(providerName("elevenlabs")).toBe("ElevenLabs");
  expect(providerName("google-gemini")).toBe("Google Gemini");
  expect(providerName("vertex")).toBe("Google Gemini");
  expect(providerName("approved-provider")).toBe("Approved provider");
  expect(providerName(" ")).toBe("An approved provider");
});

it("says each provider once, with what it does", () => {
  const lines = providerLines([
    { stage: "C2", provider: "elevenlabs", privacy_notice: NOTICE },
    { stage: "C4", provider: "google", privacy_notice: NOTICE },
    { stage: "C5", provider: "google", privacy_notice: NOTICE },
  ]);
  expect(lines).toEqual([
    "Audio: ElevenLabs",
    "Transcript and analysis: Google Gemini",
  ]);
});

it("joins two jobs for one provider and shows each notice once", () => {
  const stages = [
    { stage: "C2", provider: "google", privacy_notice: NOTICE },
    { stage: "C5", provider: "google", privacy_notice: ` ${NOTICE}` },
  ];
  expect(providerLines(stages)).toEqual([
    "Audio, transcript and analysis: Google Gemini",
  ]);
  expect(privacyNotices(stages)).toEqual([NOTICE]);
});

// 26 Oct 2026: a one-pass plan's sealed notice sent the audio to ElevenLabs while Google
// Gemini transcribes it; a notice never contradicts the provider lines.
it("leaves out a notice that names a provider the plan does not use", () => {
  const wrong =
    "Your audio goes to ElevenLabs for transcription. The transcript and supporting evidence go to Google Gemini for coaching.";
  const right =
    "Your call audio and its transcript go to Google Gemini for transcription and coaching.";
  const onePass = [
    { stage: "C2", provider: "google", privacy_notice: wrong },
    { stage: "C4", provider: "google", privacy_notice: right },
  ];
  expect(providerLines(onePass)).toEqual([
    "Audio, transcript and analysis: Google Gemini",
  ]);
  expect(privacyNotices(onePass)).toEqual([right]);
  // Where ElevenLabs does transcribe, its notice stays.
  expect(
    privacyNotices([
      { stage: "C2", provider: "elevenlabs", privacy_notice: wrong },
      { stage: "C5", provider: "google", privacy_notice: wrong },
    ]),
  ).toEqual([wrong]);
});

// Whatever a plan holds, the notices it shows are exactly those naming only
// providers that have a line (the Sign-in session, 26 Oct 2026): none naming
// a provider the lines leave out, and none dropped that matches them. Who a
// notice names is read here on its own terms, not with the module's patterns.
it("shows exactly the notices whose providers have a line", () => {
  const providers = [
    "elevenlabs",
    "google-gemini",
    "openai",
    "anthropic",
    "approved-provider",
  ];
  const notices = [
    NOTICE,
    "Your audio goes to ElevenLabs for transcription.",
    "Your call audio and its transcript go to Google Gemini for transcription and coaching.",
    "OpenAI prepares the coaching notes.",
    "Claude, by Anthropic, reviews the transcript.",
    "Your audio goes to ElevenLabs; Google Gemini writes the report.",
  ];
  const named: Record<string, RegExp> = {
    ElevenLabs: /elevenlabs/i,
    "Google Gemini": /google|gemini/i,
    OpenAI: /openai/i,
    Anthropic: /anthropic|claude/i,
  };
  for (const audio of providers)
    for (const report of providers)
      for (const first of notices)
        for (const second of notices) {
          const stages = [
            { stage: "C2", provider: audio, privacy_notice: first },
            { stage: "C5", provider: report, privacy_notice: second },
          ];
          const lines = providerLines(stages);
          const hasLine = (name: string) =>
            lines.some((line) => line.endsWith(`: ${name}`));
          const expected = [...new Set([first, second])].filter((notice) =>
            Object.entries(named).every(
              ([name, pattern]) => !pattern.test(notice) || hasLine(name),
            ),
          );
          expect(
            privacyNotices(stages),
            `${audio} and ${report}: ${first} | ${second}`,
          ).toEqual(expected);
        }
});
