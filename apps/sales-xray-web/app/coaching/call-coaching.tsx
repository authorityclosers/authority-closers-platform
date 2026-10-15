"use client";

import Link from "next/link";
import { FileSearch, FileText, GraduationCap, Users } from "lucide-react";
import { StoryCard } from "../report-visuals/visuals";
import { Empty, List, Panel, Row } from "../ui/kit";
import type { CallCoaching } from "./coaching-read";
import {
  CALL,
  CALL_PILLARS,
  FOCUS,
  NEXT,
  THEIR,
  THEIR_CALL_PILLARS,
  WHY,
} from "./coaching-copy";
import {
  dipakTake,
  FocusHero,
  LessonPanel,
  MissionPanel,
  Pillar,
  type Chip,
} from "./coaching-ui";
import { TheirCoaching } from "./coaching-voice";
import { MomentList } from "./evidence-player";
import styles from "./coaching.module.css";

const BASIS = {
  skill_evidence: FOCUS.fromSkills,
  report_suggestion: FOCUS.fromReport,
  general_practice: FOCUS.general,
  unavailable: CALL.unavailable,
} as const;

/** Where one call's focus came from, as the chip on its focus card. */
export function basisChip(basis: keyof typeof BASIS): Chip {
  return {
    text: BASIS[basis],
    tone: basis === "general_practice" ? "neutral" : "accent",
  };
}

/** Level 1: one call → one focus, its moments, a lesson and one mission. */
export function CallCoachingStory({ coaching }: { coaching: CallCoaching }) {
  const { focus, lesson, mission, practice, evidence } = coaching;
  // AC Sandbox calls are fictional records with no report page; Team lists them.
  const report = coaching.sandbox
    ? { href: "/coaching?view=team", title: CALL.backToTeam }
    : {
        href: `/analysis/calls/${coaching.submission_id}`,
        title: CALL.backToReport,
      };
  if (!focus || !lesson || !mission || !practice)
    return (
      <Panel title={CALL.title}>
        <Empty
          icon={FileSearch}
          title={CALL.notReady}
          text={CALL.notReadyText}
          action={{
            href: report.href,
            label: coaching.sandbox ? CALL.openTeam : CALL.openReport,
          }}
        />
      </Panel>
    );
  // A fictional rep's call is read by the person who imported it: "their".
  const theirs = Boolean(coaching.sandbox && coaching.rep_person_id);
  const pillars = theirs ? THEIR_CALL_PILLARS : CALL_PILLARS;
  return (
    <TheirCoaching.Provider value={theirs}>
      <div className={styles.conversation}>
        <Pillar id="coaching-focus" copy={pillars.focus}>
          <FocusHero
            label={focus.label}
            chips={[
              basisChip(coaching.basis),
              ...(coaching.sandbox ? [{ text: FOCUS.sandbox }] : []),
            ]}
            explanation={focus.explanation}
            why={focus.why_it_matters}
            reason={focus.selected_reason}
            evidenceAnchor={evidence.length ? "coaching-why" : undefined}
            lessonAnchor="coaching-better"
            mission={mission.behavior}
            missionAnchor="call-mission"
            take={dipakTake(coaching.media_clips)}
          />
        </Pillar>
        <Pillar id="coaching-why" copy={pillars.why}>
          {evidence.length ? (
            <div className={styles.card} data-flush="">
              <MomentList
                evidence={evidence}
                showCall={false}
                heading={WHY.callEvidence}
                label={CALL.moments}
                fictional={coaching.sandbox}
              />
            </div>
          ) : (
            <StoryCard>
              <p className={styles.momentNote}>
                {WHY.noTimestamp}{" "}
                <Link href={report.href}>{CALL.openReport}</Link>
              </p>
            </StoryCard>
          )}
        </Pillar>
        <LessonPanel
          copy={pillars.better}
          lesson={lesson}
          clips={coaching.media_clips}
          fallbackObservation={focus.explanation}
          strength={coaching.strength}
        />
        <MissionPanel
          id="call-mission"
          copy={pillars.next}
          mission={mission}
          practice={practice}
          foot={
            theirs ? THEIR.oneCall(coaching.rep_name ?? null) : NEXT.oneCall
          }
        />
        <Panel title={CALL.keepGoing}>
          <List label={CALL.keepGoing}>
            <Row
              icon={
                coaching.sandbox ? (
                  <Users size={15} aria-hidden="true" />
                ) : (
                  <FileText size={15} aria-hidden="true" />
                )
              }
              title={report.title}
              href={report.href}
              meta={
                coaching.other_suggestions
                  ? [CALL.moreSuggestions(coaching.other_suggestions)]
                  : undefined
              }
            />
            {coaching.sandbox && coaching.rep_person_id ? (
              <Row
                icon={<GraduationCap size={15} aria-hidden="true" />}
                title={CALL.repAcross(coaching.rep_name ?? null)}
                href={`/coaching?person=${coaching.rep_person_id}`}
              />
            ) : (
              <Row
                icon={<GraduationCap size={15} aria-hidden="true" />}
                title={CALL.mineAcross}
                href="/coaching"
              />
            )}
          </List>
        </Panel>
      </div>
    </TheirCoaching.Provider>
  );
}
