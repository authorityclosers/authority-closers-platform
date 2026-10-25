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
