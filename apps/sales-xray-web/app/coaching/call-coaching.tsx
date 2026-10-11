"use client";

import Link from "next/link";
import { FileSearch, FileText, GraduationCap, Users } from "lucide-react";
import { StoryCard } from "../report-visuals/visuals";
import { Empty, List, Panel, Row } from "../ui/kit";
import type { CallCoaching } from "./coaching-read";
import {
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
  unavailable: "Unavailable",
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
    ? { href: "/coaching?view=team", title: "Back to team coaching" }
    : {
        href: `/analysis/calls/${coaching.submission_id}`,
        title: "Back to this call’s report",
      };
  if (!focus || !lesson || !mission || !practice)
    return (
      <Panel title="Coaching for this call">
        <Empty
          icon={FileSearch}
          title="This call’s coaching isn’t ready"
          text="Its moments are hidden or not ready yet. The report shows what’s there."
          action={{
            href: report.href,
            label: coaching.sandbox ? "Open team coaching" : "Open the report",
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
                label="Moments from this call"
                fictional={coaching.sandbox}
              />
            </div>
          ) : (
            <StoryCard>
              <p className={styles.momentNote}>
                {WHY.noTimestamp}{" "}
                <Link href={report.href}>Open the report</Link>
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
        <Panel title="Keep going">
          <List label="Keep going">
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
                  ? [
                      `${coaching.other_suggestions} more suggestion${coaching.other_suggestions === 1 ? "" : "s"} there; Coaching keeps one focus`,
                    ]
                  : undefined
              }
            />
            {coaching.sandbox && coaching.rep_person_id ? (
              <Row
                icon={<GraduationCap size={15} aria-hidden="true" />}
                title={`${coaching.rep_name ?? "This rep"}’s coaching across calls`}
                href={`/coaching?person=${coaching.rep_person_id}`}
              />
            ) : (
              <Row
                icon={<GraduationCap size={15} aria-hidden="true" />}
                title="My coaching across calls"
                href="/coaching"
              />
            )}
          </List>
        </Panel>
      </div>
    </TheirCoaching.Provider>
  );
}
