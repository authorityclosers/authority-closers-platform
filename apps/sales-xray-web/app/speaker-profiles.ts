"use client";

import {
  useCallback,
  useMemo,
  useSyncExternalStore,
  type CSSProperties,
} from "react";

import type {
  Finding,
  SalesReport,
  Transcript,
  TranscriptSegment,
} from "./report-contract";
import { speakerIcon } from "./speaker-icons";

export type SpeakerRole = "you" | "salesperson" | "prospect" | "other";
export type SpeakerProfile = Readonly<{
  name: string;
  role: SpeakerRole | null;
  icon: string | null;
}>;
export type SpeakerProfiles = Readonly<Record<string, SpeakerProfile>>;

export const SPEAKERS_EVENT = "sales-xray:speakers";
export const MAX_SPEAKER_NAME = 60;

/**
 * One clearly different colour per voice: teal, violet, amber, raspberry.
 * Chips, lanes, the talk-ratio bar, the peek and avatars all read it.
 */
const VOICE_COLOURS = [
  "var(--lx-teal)",
  "var(--lx-missed)",
  "var(--lx-warning)",
  "var(--lx-objection)",
];

export function voiceStyle(voice: number): CSSProperties {
  return {
    "--voice": VOICE_COLOURS[voice] ?? VOICE_COLOURS[VOICE_COLOURS.length - 1],
  } as CSSProperties;
}

// Until the account API stores speaker names (AUT-311), a call's speaker
// profiles are kept on this device only.
const storageKey = (callId: string) => `ac.xray.speakers.v1:${callId}`;

function parse(raw: string | null): SpeakerProfiles {
  if (!raw) return {};
  try {
    const data: unknown = JSON.parse(raw);
    if (!data || typeof data !== "object" || Array.isArray(data)) return {};
    const profiles: Record<string, SpeakerProfile> = {};
    for (const [id, value] of Object.entries(data)) {
      if (!value || typeof value !== "object") continue;
      const { name, role, icon } = value as Record<string, unknown>;
      profiles[id] = {
        name:
          typeof name === "string"
            ? name.trim().slice(0, MAX_SPEAKER_NAME)
            : "",
        role:
          role === "you" ||
          role === "salesperson" ||
          role === "prospect" ||
          role === "other"
            ? role
            : null,
        icon: typeof icon === "string" && speakerIcon(icon) ? icon : null,
      };
    }
    return profiles;
  } catch {
    return {};
  }
}

function readRaw(callId: string | null): string | null {
  if (!callId) return null;
  try {
    return localStorage.getItem(storageKey(callId));
  } catch {
    return null;
  }
}

export function readSpeakerProfiles(callId: string | null): SpeakerProfiles {
  return parse(readRaw(callId));
}

/** Removes this call's local speaker names and roles after deletion succeeds. */
export function clearSpeakerProfiles(callId: string): boolean {
  try {
    localStorage.removeItem(storageKey(callId));
  } catch {
    return false;
  }
  window.dispatchEvent(new CustomEvent(SPEAKERS_EVENT, { detail: { callId } }));
  return true;
}

/**
 * Merges changes into a call's speaker profiles. Only one speaker can be
 * "you": naming someone you clears that role from everyone else.
 */
export function saveSpeakerProfiles(
  callId: string,
  changes: SpeakerProfiles,
): boolean {
  const claimsYou = Object.values(changes).some(
    (profile) => profile.role === "you",
  );
  const next: Record<string, SpeakerProfile> = {};
  for (const [id, profile] of Object.entries(readSpeakerProfiles(callId)))
    next[id] =
      claimsYou && profile.role === "you" && !(id in changes)
        ? { ...profile, role: null }
        : profile;
  for (const [id, profile] of Object.entries(changes))
    next[id] = {
      name: profile.name.trim().slice(0, MAX_SPEAKER_NAME),
      role: profile.role,
      icon: speakerIcon(profile.icon) ? profile.icon : null,
    };
  try {
    localStorage.setItem(storageKey(callId), JSON.stringify(next));
  } catch {
    return false;
  }
  window.dispatchEvent(new CustomEvent(SPEAKERS_EVENT, { detail: { callId } }));
  return true;
}

function subscribe(notify: () => void) {
  window.addEventListener(SPEAKERS_EVENT, notify);
  window.addEventListener("storage", notify);
  return () => {
    window.removeEventListener(SPEAKERS_EVENT, notify);
    window.removeEventListener("storage", notify);
  };
}

/** A call's speaker names, roles and icons, live across the page. */
export function useSpeakerProfiles(callId: string | null) {
  const raw = useSyncExternalStore(
    subscribe,
    () => readRaw(callId),
    () => null,
  );
  const profiles = useMemo(() => parse(raw), [raw]);
  const save = useCallback(
    (changes: SpeakerProfiles) =>
      callId ? saveSpeakerProfiles(callId, changes) : false,
    [callId],
  );
  return { profiles, save, canSave: callId !== null };
}

export function firstName(name: string | null | undefined): string | null {
  const first = name?.trim().split(/\s+/)[0];
  return first ? first : null;
}

export function initials(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return parts
    .slice(0, 2)
    .map((part) => Array.from(part)[0])
    .join("")
    .toLocaleUpperCase();
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export type YouSuggestion = Readonly<{
  speakerId: string;
  reason: "introduction" | "coaching";
}>;

function leader(scores: Map<string, number>, minimum: number) {
  const ranked = [...scores.entries()].sort((a, b) => b[1] - a[1]);
  const [top, next] = ranked;
  if (!top || top[1] < minimum) return null;
  if (next && next[1] >= top[1]) return null;
  return top[0];
}

function speakerOf(
  segments: TranscriptSegment[],
  evidence: { segment_id: string; start_ms: number },
) {
  const cited =
    segments.find((segment) => segment.id === evidence.segment_id) ??
    segments.find(
      (segment) =>
        segment.start_ms <= evidence.start_ms &&
        evidence.start_ms < segment.end_ms,
    );
  return cited?.speaker_id ?? null;
}

/**
 * Which voice is probably the account holder, from what was said, never from
 * how anyone sounds: an introduction with your name ("this is Suyash") or
 * someone greeting you by name; failing that, the voice the report's
 * coaching (strengths and improvements) keeps quoting. A suggestion only:
 * the person confirms it.
 */
export function suggestYou(
  transcript: Transcript,
  report: SalesReport,
  accountName: string | null,
): YouSuggestion | null {
  const voices = [
    ...new Set(
      transcript.segments
        .map((segment) => segment.speaker_id)
        .filter((id): id is string => id !== null),
    ),
  ];
  if (voices.length < 2) return null;

  const name = firstName(accountName);
  if (name && name.length >= 2) {
    const quoted = escapeRegExp(name);
    const introduces = new RegExp(
      `(?:\\b(?:this is|i am|i'm|my name is|myself)\\s+${quoted}\\b|\\b${quoted}\\s+(?:here|speaking|this side)\\b|(?:मैं|मेरा नाम)\\s+${quoted})`,
      "i",
    );
    const greets = new RegExp(
      `(?:\\b(?:hi|hello|hey|thanks|thank you|namaste|namaskar)\\s+${quoted}\\b|\\b${quoted}\\s+(?:ji|sir|bhai|bhaiya)\\b)`,
      "i",
    );
    const scores = new Map<string, number>();
    for (const segment of transcript.segments) {
      const voice = segment.speaker_id;
      if (voice === null) continue;
      if (introduces.test(segment.text))
        scores.set(voice, (scores.get(voice) ?? 0) + 3);
      else if (greets.test(segment.text) && voices.length === 2)
        for (const other of voices)
          if (other !== voice) scores.set(other, (scores.get(other) ?? 0) + 2);
    }
    const named = leader(scores, 2);
    if (named) return { speakerId: named, reason: "introduction" };
  }

  const coaching = new Map<string, number>();
  const findings: Finding[] = [...report.strengths, ...report.improvements];
  for (const finding of findings)
    for (const evidence of finding.evidence) {
      const voice = speakerOf(transcript.segments, evidence);
      if (voice !== null) coaching.set(voice, (coaching.get(voice) ?? 0) + 1);
    }
  const total = [...coaching.values()].reduce((sum, value) => sum + value, 0);
  const coached = leader(coaching, 2);
  if (coached && (coaching.get(coached) ?? 0) / total >= 0.6)
    return { speakerId: coached, reason: "coaching" };
  return null;
}

// Words that follow "my name is" / "this is" / greetings but are not names.
const NOT_NAMES = new Set(
  [
    "है",
    "हूं",
    "हूँ",
    "से",
    "जी",
    "आप",
    "मैं",
    "हम",
    "हां",
    "सर",
    "मेरा",
    "मेरी",
    "sir",
    "ji",
    "madam",
    "the",
    "a",
    "an",
    "there",
    "my",
    "i",
    "i'm",
    "your",
    "calling",
    "speaking",
    "just",
    "happy",
    "glad",
    "looking",
    "sure",
    "sorry",
    "fine",
    "good",
    "great",
    "well",
    "ok",
    "okay",
    "not",
    "very",
    "really",
    "also",
    "interested",
    "busy",
    "going",
    "trying",
    "back",
    "available",
    "free",
    "here",
    "regarding",
    "about",
    "from",
    "for",
    "with",
    "dr",
    "dr.",
    "mr",
    "mr.",
    "mrs",
    "ms",
  ].map((word) => word.toLocaleLowerCase()),
);
const NAME = "([\\p{L}\\p{M}][\\p{L}\\p{M}'’-]*)(?![\\p{L}\\p{M}])";
// Phrases must start a word: "Hi am I…" is not "I am …".
const START = "(?<![\\p{L}\\p{M}])";
const SEGMENT_START = "^[\\s\\p{P}]*";
const NAME_SUFFIX =
  "(?:here|speaking|this side|बोल रहा(?:\\s+(?:हूं|हूँ))?|बोल रही(?:\\s+(?:हूं|हूँ))?|bol raha|bol rahi)";
const SELF_INTRODUCTIONS = [
  new RegExp(`${START}(?:मेरा नाम|my name is|myself|this is)\\s+${NAME}`, "iu"),
  new RegExp(`${START}(?:i am|i'm)\\s+${NAME}`, "iu"),
  new RegExp(
    `${START}(?:मैं|main)\\s+${NAME}\\s+(?:बोल रहा|बोल रही|bol raha|bol rahi)`,
    "iu",
  ),
  new RegExp(`${SEGMENT_START}${NAME}\\s+${NAME_SUFFIX}(?=\\s|$|[,.!?])`, "iu"),
  new RegExp(
    `${START}(?:hi|hello|hey)\\s+${NAME}\\s+${NAME_SUFFIX}(?=\\s|$|[,.!?])`,
    "iu",
  ),
];
const GREETINGS = [
  new RegExp(`${START}${NAME}\\s+जी\\s*,?\\s*(?:नमस्ते|नमस्कार)`, "u"),
  new RegExp(
    `${START}(?:नमस्ते|नमस्कार|hello|hi|hey)\\s+${NAME}(\\s+जी)?(?!\\s+${NAME_SUFFIX}(?=\\s|$|[,.!?]))`,
    "iu",
  ),
];
/** Introductions happen early: only the first minutes are read. */
const NAME_WINDOW_MS = 150_000;

function nameFrom(
  match: RegExpMatchArray | null,
  requireNameStyle = false,
): string | null {
  const word = match?.[1]?.trim();
  if (!word || Array.from(word).length < 2) return null;
  if (NOT_NAMES.has(word.toLocaleLowerCase())) return null;
  if (
    requireNameStyle &&
    !/^(?=\p{Script=Latin})\p{Lu}[\p{L}\p{M}'’-]*$/u.test(word) &&
    !/^(?=\p{Script=Devanagari})\p{L}[\p{L}\p{M}'’-]*$/u.test(word)
  )
    return null;
  return word;
}

export type SpokenNames = Readonly<{
  /** A spoken name per speaker label, spelled as spoken. */
  names: Readonly<Record<string, string>>;
  /** Speaker labels that introduced themselves, in order. */
  introducers: readonly string[];
}>;

/**
 * Names people say about themselves or call each other in the opening of the
 * call: "मेरा नाम मानस है" names its own speaker; "नंदलाल जी नमस्ते" names the
 * other person on a two-person call. Only a suggestion for the person to
 * confirm; never read from how anyone sounds.
 */
export function detectSpokenNames(transcript: Transcript): SpokenNames {
  const voices = [
    ...new Set(
      transcript.segments
        .map((segment) => segment.speaker_id)
        .filter((id): id is string => id !== null),
    ),
  ];
  const names: Record<string, string> = {};
  const introducers: string[] = [];
  for (const segment of transcript.segments) {
    if (segment.start_ms > NAME_WINDOW_MS) break;
    const voice = segment.speaker_id;
    if (voice === null) continue;
    for (const [index, pattern] of SELF_INTRODUCTIONS.entries()) {
      const requireNameStyle = index === 1 || index === 3 || index === 4;
      const name = nameFrom(segment.text.match(pattern), requireNameStyle);
      if (!name) continue;
      if (!names[voice]) names[voice] = name;
      if (!introducers.includes(voice)) introducers.push(voice);
    }
    if (voices.length !== 2) continue;
    const other = voices.find((id) => id !== voice);
    for (const pattern of GREETINGS) {
      const match = segment.text.match(pattern);
      const name = nameFrom(match);
      if (!name || !other || names[other]) continue;
      const honorific =
        Boolean(match?.[2]) ||
        /जी\s*,?\s*(?:नमस्ते|नमस्कार)/u.test(match?.[0] ?? "");
      names[other] = honorific ? `${name} जी` : name;
    }
  }
  return { names, introducers };
}

/** Whether a spoken name is the account holder's own first name. */
export function isAccountName(
  spoken: string | undefined,
  accountName: string | null,
): boolean {
  const first = firstName(accountName);
  if (!spoken || !first) return false;
  const bare = spoken.replace(/\s+जी$/u, "").toLocaleLowerCase();
  return bare === first.toLocaleLowerCase();
}

export const ROLE_WORDS: Readonly<Record<SpeakerRole, string>> = {
  you: "You",
  salesperson: "Salesperson",
  prospect: "Prospect",
  other: "Other",
};

/** The name to show for a speaker: typed name, you, else "Speaker n". */
export function speakerName(
  index: number,
  profile: SpeakerProfile | undefined,
  accountName: string | null,
): string {
  if (profile?.name) return profile.name;
  if (profile?.role === "you") return firstName(accountName) ?? "You";
  return `Speaker ${index + 1}`;
}
