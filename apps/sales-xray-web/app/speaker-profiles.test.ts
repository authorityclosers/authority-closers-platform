import { afterEach, expect, it } from "vitest";

import fixture from "../tests/fixtures/dipak-overview.json";
import type { SalesReport, Transcript } from "./report-contract";
import { searchSpeakerIcons, suggestProspectIcon } from "./speaker-icons";
import {
  detectSpokenNames,
  initials,
  isAccountName,
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

it("reads spoken names from a Hindi opening, spelled as spoken", () => {
  const transcript = call([
    ["s0", "लोहर जी से हो रही है अहमदाबाद से।"],
    ["s1", "हां।"],
    ["s0", "नंदलाल जी नमस्ते मेरा नाम मानस है। मैं team से बोल रहा हूं।"],
  ]);
  expect(detectSpokenNames(transcript)).toEqual({
    names: { s0: "मानस", s1: "नंदलाल जी" },
    introducers: ["s0"],
  });
  expect(isAccountName("मानस", "Suyash Rao")).toBe(false);
  expect(isAccountName("Suyash", "Suyash Rao")).toBe(true);
});

it("does not read ordinary phrases after a generic I am as names", () => {
  for (const text of [
    "I am just calling about your enquiry.",
    "I'm happy to help.",
  ]) {
    expect(
      detectSpokenNames(
        call([
          ["s0", text],
          ["s1", "Hello."],
        ]),
      ),
    ).toEqual({
      names: {},
      introducers: [],
    });
  }
});

it("accepts capitalized Latin or Devanagari names after a generic I am", () => {
  expect(
    detectSpokenNames(
      call([
        ["latin", "I am Élodie."],
        ["lowercase", "I am rahul."],
        ["hindi", "I am मानस."],
        ["other", "Hello."],
      ]),
    ),
  ).toEqual({
    names: { latin: "Élodie", hindi: "मानस" },
    introducers: ["latin", "hindi"],
  });
});

it("treats greetings with here and speaking suffixes as self introductions", () => {
  for (const text of [
    "Hello Rahul here",
    "Hi Rahul this side",
    "Hello Rahul speaking",
    "Hello Rahul बोल रहा हूं",
    "Hello Rahul बोल रही हूँ",
    "Hello Rahul bol raha",
    "Hello Rahul bol rahi",
  ]) {
    expect(
      detectSpokenNames(
        call([
          ["s0", text],
          ["s1", "Hello."],
        ]),
      ),
    ).toEqual({
      names: { s0: "Rahul" },
      introducers: ["s0"],
    });
  }
});

it("accepts bare name suffixes only at the start of an introduction", () => {
  for (const text of [
    "Rahul here",
    "Rahul speaking",
    "राहुल बोल रहा हूं",
    "मैं राहुल बोल रहा",
  ]) {
    expect(
      detectSpokenNames(
        call([
          ["s0", text],
          ["s1", "Hello."],
        ]),
      ),
    ).toEqual({
      names: { s0: text.includes("Rahul") ? "Rahul" : "राहुल" },
      introducers: ["s0"],
    });
  }
});

it("does not treat phrases or mid-sentence words as name suffixes", () => {
  for (const text of [
    "Hello there.",
    "Thanks for being here.",
    "Are you still speaking to other vendors?",
    "Who is speaking?",
    "I'm here to help.",
    "Is anyone here?",
    "rahul here",
  ]) {
    expect(
      detectSpokenNames(
        call([
          ["s0", text],
          ["s1", "Hello."],
        ]),
      ),
    ).toEqual({
      names: {},
      introducers: [],
    });
  }
});

it("keeps counterpart greetings distinct from self introductions", () => {
  expect(
    detectSpokenNames(
      call([
        ["s0", "Hello Rahul, how are you"],
        ["s1", "Hi."],
      ]),
    ).names,
  ).toEqual({ s1: "Rahul" });
  expect(
    detectSpokenNames(
      call([
        ["s0", "नंदलाल जी नमस्ते"],
        ["s1", "जी"],
      ]),
    ).names,
  ).toEqual({ s1: "नंदलाल जी" });
  expect(
    detectSpokenNames(
      call([
        ["s0", "Hello Rahul"],
        ["s1", "Hi."],
      ]),
    ).names,
  ).toEqual({ s1: "Rahul" });
  expect(
    detectSpokenNames(
      call([
        ["s0", "नमस्ते राहुल जी"],
        ["s1", "जी नमस्ते"],
      ]),
    ).names,
  ).toEqual({ s1: "राहुल जी" });
});

it("never takes filler words for names", () => {
  const transcript = call([
    ["s0", "Hello sir, this is regarding your enquiry. नमस्ते मेरा नाम है"],
    ["s1", "हां बोलो"],
  ]);
  expect(detectSpokenNames(transcript).names).toEqual({});
});
