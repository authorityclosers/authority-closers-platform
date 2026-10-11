"use client";

import Link from "next/link";
import { FileSearch, FileText, GraduationCap, Users } from "lucide-react";
import { Empty, List, Panel, Row } from "../ui/kit";
import type { CallCoaching } from "./coaching-read";
import { CALL_PILLARS, FOCUS, NEXT, WHY } from "./coaching-copy";
import { FocusHero, LessonPanel, MissionPanel, Pillar } from "./coaching-ui";
import { MomentList } from "./evidence-player";
import styles from "./coaching.module.css";

const BASIS = {
  skill_evidence: FOCUS.fromSkills,
  report_suggestion: FOCUS.fromReport,
  general_practice: FOCUS.general,
  unavailable: "Unavailable",
} as const;

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
          title="This call’s coaching is unavailable"
          text="Its evidence is withheld or not ready. The report shows what is available."
          action={{
            href: report.href,
            label: coaching.sandbox ? "Open team coaching" : "Open the report",
          }}
        />
      </Panel>
    );
  return (
    <div className={styles.conversation}>
      <Pillar id="coaching-focus" copy={CALL_PILLARS.focus}>
        <FocusHero
          label={focus.label}
          chips={[
            {
              text: BASIS[coaching.basis],
              tone:
                coaching.basis === "general_practice" ? "neutral" : "accent",
            },
            ...(coaching.sandbox ? [{ text: FOCUS.sandbox }] : []),
          ]}
          explanation={focus.explanation}
          why={focus.why_it_matters}
          reason={focus.selected_reason}
          mission={mission.behavior}
          missionAnchor="call-mission"
        />
      </Pillar>
      <Pillar
        id="coaching-why"
        copy={CALL_PILLARS.why}
        aside={
          evidence.length
            ? `${evidence.length} moment${evidence.length === 1 ? "" : "s"}`
            : undefined
        }
      >
        {evidence.length ? (
          <div className={styles.card} data-flush="">
            <MomentList
              evidence={evidence}
              showCall={false}
              label="Moments from this call"
              fictional={coaching.sandbox}
            />
          </div>
        ) : (
          <div className={styles.card}>
            <p className={styles.momentNote}>
              {WHY.noTimestamp} <Link href={report.href}>Open the report</Link>
            </p>
          </div>
        )}
      </Pillar>
      <LessonPanel
        copy={CALL_PILLARS.better}
        lesson={lesson}
        clips={coaching.media_clips}
        fallbackObservation={focus.explanation}
        strength={coaching.strength}
      />
      <MissionPanel
        id="call-mission"
        copy={CALL_PILLARS.next}
        mission={mission}
        practice={practice}
        foot={NEXT.oneCall}
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
  );
}
