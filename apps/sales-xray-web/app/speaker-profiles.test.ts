import { afterEach, expect, it } from "vitest";

import fixture from "../tests/fixtures/dipak-overview.json";
import type { SalesReport, Transcript } from "./report-contract";
import { searchSpeakerIcons, suggestProspectIcon } from "./speaker-icons";
import {
  initials,
  readSpeakerProfiles,
  saveSpeakerProfiles,
  suggestYou,
} from "./speaker-profiles";

const CALL = "7d1b4f0e-2c3a-4b5d-9e6f-0a1b2c3d4e5f";
const report = fixture.report as SalesReport;
const base = fixture.transcript as Transcript;

afterEach(() => localStorage.clear());

function call(texts: Array<[string, string]>): Transcript {
  return {
    ...base,
    segments: texts.map(([speaker, text], index) => ({
      id: `seg-${index}`,
      speaker_id: speaker,
      start_ms: index * 1000,
      end_ms: index * 1000 + 900,
      text,
    })),
  };
}

it("keeps only one speaker as you", () => {
  saveSpeakerProfiles(CALL, {
    a: { name: "Suyash", role: "you", icon: null },
    b: { name: "Rahul", role: "prospect", icon: "carpentry" },
  });
  saveSpeakerProfiles(CALL, { b: { name: "Rahul", role: "you", icon: null } });
  const saved = readSpeakerProfiles(CALL);
  expect(saved.a).toEqual({ name: "Suyash", role: null, icon: null });
  expect(saved.b.role).toBe("you");
});

it("ignores tampered or unknown stored values", () => {
  localStorage.setItem(
    `ac.xray.speakers.v1:${CALL}`,
    JSON.stringify({
      a: { name: "  x".repeat(50), role: "boss", icon: "not-an-icon" },
      b: "nonsense",
    }),
  );
  const saved = readSpeakerProfiles(CALL);
  expect(saved.a.role).toBeNull();
  expect(saved.a.icon).toBeNull();
  expect(saved.a.name.length).toBeLessThanOrEqual(60);
  expect(saved.b).toBeUndefined();
  localStorage.setItem(`ac.xray.speakers.v1:${CALL}`, "{not json");
  expect(readSpeakerProfiles(CALL)).toEqual({});
});

it("suggests you from your own introduction", () => {
  const transcript = call([
    ["s0", "Hi, am I speaking with Rahul?"],
    ["s1", "Yes, speaking."],
    ["s0", "Great, this is Suyash from Authority Closers."],
  ]);
  expect(suggestYou(transcript, report, "Suyash Rao")).toEqual({
    speakerId: "s0",
    reason: "introduction",
  });
});

it("suggests you when the other person greets you by name", () => {
  const transcript = call([
    ["s0", "Hello?"],
    ["s1", "Hello Suyash, good to hear from you."],
    ["s0", "Thanks for your time today."],
  ]);
  expect(suggestYou(transcript, report, "Suyash")?.speakerId).toBe("s0");
});

it("makes no suggestion without evidence either way", () => {
  const transcript = call([
    ["s0", "Hello there."],
    ["s1", "Hello."],
  ]);
  expect(
    suggestYou(
      transcript,
      { ...report, strengths: [], improvements: [] },
      null,
    ),
  ).toBeNull();
  // One voice: nothing to tell apart.
  expect(suggestYou(call([["s0", "Only me"]]), report, "Suyash")).toBeNull();
});

it("falls back to the voice the coaching keeps quoting", () => {
  const transcript = call([
    ["rep", "Tell me about your current process."],
    ["buyer", "We do it by hand."],
    ["rep", "What does that cost you each month?"],
  ]);
  const cite = (id: string) => ({
    segment_id: id,
    quote: "",
    start_ms: 0,
    end_ms: 0,
  });
  const coached = {
    ...report,
    strengths: [{ title: "Asked", explanation: "", evidence: [cite("seg-0")] }],
    improvements: [
      { title: "Quantify", explanation: "", evidence: [cite("seg-2")] },
    ],
  } as SalesReport;
  expect(suggestYou(transcript, coached, null)).toEqual({
    speakerId: "rep",
    reason: "coaching",
  });
});

it("picks a prospect icon from the report's own words", () => {
  expect(
    suggestProspectIcon(
      "You spoke with a carpentry business owner about furniture orders.",
    ),
  ).toBe("carpentry");
  expect(suggestProspectIcon("A general discussion.")).toBe("business");
  expect(searchSpeakerIcons("salon").map((icon) => icon.key)).toContain(
    "salon",
  );
  expect(initials("Suyash Rao")).toBe("SR");
  expect(initials("")).toBe("?");
});
