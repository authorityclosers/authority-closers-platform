"use client";

import {
  Briefcase,
  CalendarCheck,
  CheckSquare,
  GraduationCap,
  IndianRupee,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useMemo, type CSSProperties, type ReactNode } from "react";

import { useCallFacts } from "./call-facts";
import { promiseId, usePromisesDone } from "./call-signals";
import { voicesOf } from "./call-data";
import type { SalesReport, Transcript } from "./report-contract";
import { findEntities } from "./report-entities";
import { goToReportSection } from "./report-reading-context";
import { confirmedRoles, promises } from "./sales-signals";
import { getShellState } from "./shell/shell-store";
import { SpeakerAvatar } from "./speaker-avatar";
import { SPEAKER_ICONS, type SpeakerIcon } from "./speaker-icons";
import { speakerName, useSpeakerProfiles } from "./speaker-profiles";
import styles from "./call-context.module.css";

type Tile = {
  key: string;
  label: string;
  value: ReactNode;
  /** Shown when the value was only heard, not confirmed by a person. */
  heard?: boolean;
  icon: ReactNode;
  tone: string;
  go: string;
  /** What the tile says when the call gave no value. */
  empty: string;
};

const icon = (Icon: LucideIcon) => <Icon size={14} aria-hidden="true" />;

/** The report's own sentences, in reading order, for finding mentions. */
function reportTexts(report: SalesReport): string[] {
  const overview = report.overview;
  const change = overview?.conversation_change;
  return [
    change?.change.text,
    change?.after.text,
    change?.before.text,
    overview?.outcome?.text,
    overview?.diagnosis?.text,
    ...(overview?.rewatch ?? []).map((item) => item.text),
    change?.possible_effect,
    report.summary,
    report.verdict,
  ].filter((text): text is string => Boolean(text));
}

export function firstEntity(texts: string[], kind: string, test?: RegExp) {
  for (const text of texts)
    for (const part of findEntities(text))
      if (
        typeof part !== "string" &&
        part.kind === kind &&
        (!test || test.test(part.text))
      )
        return part.text;
  return null;
}

const BUSINESS_NAMED =
  /([\p{L}-]+)\s+(?:(?:का|की|के|ka|ki|ke)\s+)?(?:business|बिज़नेस|बिजनेस|व्यवसाय|व्यापार|धंधा|company|कंपनी|shop|दुकान|firm)/giu;

// Second-person words just before a business name: the seller asking about
// the prospect's own business ("आपका carpentry का business", "your salon").
const ADDRESSED =
  /(?:आपका|आपकी|आपके|आपने|तुमचा|तुमची|तुमचं|तुमच्या|your|you run|you have)[^.?!।]{0,40}$/iu;

/**
 * The industry named outright in some text, e.g. "carpentry का business".
 * With `addressed`, only a business named to the listener ("your ...").
 */
export function businessNamed(
  text: string,
  addressed = false,
): SpeakerIcon | null {
  for (const match of text.matchAll(BUSINESS_NAMED)) {
    if (addressed && !ADDRESSED.test(text.slice(0, match.index ?? 0))) continue;
    const word = match[1].toLocaleLowerCase();
    const found = SPEAKER_ICONS.find(
      (item) => !item.generic && item.keywords.includes(word),
    );
    if (found) return found;
  }
  return null;
}

/**
 * The prospect's business, from evidence about the prospect only: their own
 * words, or the seller naming it to them. Another speaker's business never
 * counts. Nothing without confirmed roles.
 */
export function prospectBusiness(
  segments: ReadonlyArray<{ speaker_id: string | null; text: string }>,
  roles: { seller: string; prospect: string } | null,
): SpeakerIcon | null {
  if (!roles) return null;
  for (const segment of segments) {
    const found =
      segment.speaker_id === roles.prospect
        ? businessNamed(segment.text)
        : segment.speaker_id === roles.seller
          ? businessNamed(segment.text, true)
          : null;
    if (found) return found;
  }
  return null;
}

/**
 * The call at a glance, in the space beside the title: who the prospect is,
 * their business, what was sold, the money talked about, the promises made
 * and the next step. Every value comes from this call (report, transcript or
 * what you confirmed); nothing is guessed beyond what was said.
 */
export function CallContext({
  callId,
  report,
  transcript,
}: {
  callId: string | null;
  report: SalesReport;
  transcript: Transcript;
}) {
  const { profiles } = useSpeakerProfiles(callId);
  const { facts } = useCallFacts(callId);
  const done = usePromisesDone(callId);
  const accountName = getShellState().profileName;
  const voices = useMemo(() => voicesOf(transcript), [transcript]);
  const texts = useMemo(() => reportTexts(report), [report]);
  const roles = confirmedRoles(
    voices,
    Object.fromEntries(voices.map((id) => [id, profiles[id]?.role])),
  );
  const promised = useMemo(
    () => (roles ? promises(transcript, roles) : []),
    // roles comes from saved profiles; its two ids are the real inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transcript, roles?.seller, roles?.prospect],
  );
  // Their business only when named outright about the prospect; loose
  // keyword counts guessed wrong.
  const heardBusiness = useMemo(
    () => prospectBusiness(transcript.segments, roles),
    // roles comes from saved profiles; its two ids are the real inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transcript, roles?.seller, roles?.prospect],
  );

  const prospectId =
    roles?.prospect ?? voices.find((id) => profiles[id]?.role === "prospect");
  const industryLabel = facts.values.industry?.trim() || null;
  const industry =
    SPEAKER_ICONS.find((item) => item.label === industryLabel) ??
    heardBusiness ??
    undefined;
  const selling = firstEntity(texts, "program");
  const money = facts.values.budget
    ? `Budget ${facts.values.budget}`
    : firstEntity(texts, "money", /\d/);
  const outcomeText = report.overview?.outcome?.text;
  const when = outcomeText ? firstEntity([outcomeText], "date") : null;
  // Only an explicit next step: a saved one, or a dated follow-up. An
  // outcome such as "No sale" is not a next step.
  const next =
    facts.values.next?.trim() ||
    (report.overview?.outcome?.kind === "follow_up" && when
      ? `Follow-up ${when}`
      : null);
  const ticked = promised.filter((item) => done.has(promiseId(item))).length;

  const tiles: Tile[] = [
    {
      key: "prospect",
      label: "Prospect",
      value: prospectId
        ? speakerName(
            voices.indexOf(prospectId),
            profiles[prospectId],
            accountName,
          )
        : null,
      icon: prospectId ? (
        <SpeakerAvatar
          voice={voices.indexOf(prospectId)}
          profile={profiles[prospectId]}
          youName={accountName}
          size={22}
        />
      ) : (
        icon(UserRound)
      ),
      tone: "violet",
      go: "prospect",
      empty: "Name them",
    },
    {
      key: "business",
      label: "Business",
      value: industry?.label ?? industryLabel,
      heard: !facts.confirmed.industry,
      icon: industry ? (
        <industry.Icon size={14} aria-hidden="true" />
      ) : (
        icon(Briefcase)
      ),
      tone: "teal",
      go: "prospect",
      empty: "Add",
    },
    {
      key: "selling",
      label: "Selling",
      value: selling,
      icon: icon(GraduationCap),
      tone: "violet",
      go: "moments",
      empty: "Not named",
    },
    {
      key: "money",
      label: facts.values.budget ? "Budget" : "Money talked about",
      value: money,
      heard: !facts.values.budget,
      icon: icon(IndianRupee),
      tone: "amber",
      go: "prospect",
      empty: "None heard",
    },
    {
      key: "promises",
      label: "Promises",
      value: roles
        ? promised.length
          ? `${promised.length} made · ${ticked} done`
          : "None found"
        : null,
      icon: icon(CheckSquare),
      tone: "blue",
      go: "signals",
      empty: "Mark who's who",
    },
    {
      key: "next",
      label: "Next step",
      value: next,
      icon: icon(CalendarCheck),
      tone: "teal",
      go: "next-call-plan",
      empty: "Add",
    },
  ];

  return (
    <div className={styles.context} aria-label="This call at a glance">
      {tiles.map((tile, index) => (
        <button
          key={tile.key}
          type="button"
          className={styles.tile}
          data-tone={tile.tone}
          data-empty={tile.value ? undefined : ""}
          style={{ "--i": index } as CSSProperties}
          onClick={() => goToReportSection(tile.go)}
          title={
            tile.value && tile.heard
              ? "Heard on the call. Confirm it in Prospect."
              : undefined
          }
        >
          <span className={styles.icon}>{tile.icon}</span>
          <span className={styles.text}>
            <small>{tile.label}</small>
            <b title={typeof tile.value === "string" ? tile.value : undefined}>
              {tile.value ?? tile.empty}
            </b>
          </span>
        </button>
      ))}
    </div>
  );
}
