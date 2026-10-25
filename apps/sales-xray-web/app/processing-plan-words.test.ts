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
