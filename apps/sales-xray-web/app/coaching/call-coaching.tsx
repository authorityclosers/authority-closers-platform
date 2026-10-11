"use client";

import Link from "next/link";
import { FileSearch, FileText, GraduationCap, Users } from "lucide-react";
import { Empty, List, Panel, Row } from "../ui/kit";
import type { CallCoaching } from "./coaching-read";
import { FocusHero, LessonPanel, MissionPanel } from "./coaching-ui";
import { MomentList } from "./evidence-player";
import styles from "./coaching.module.css";

const BASIS = {
  skill_evidence: "From this call’s skill evidence",
  report_suggestion: "From this call’s report",
  general_practice: "General practice",
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
      <FocusHero
        heading="One focus for this call"
        label={focus.label}
        badges={[
          {
            text: BASIS[coaching.basis],
            tone: coaching.basis === "general_practice" ? "neutral" : "accent",
          },
          ...(coaching.sandbox ? [{ text: "Fictional AC Sandbox" }] : []),
        ]}
        explanation={focus.explanation}
        why={focus.why_it_matters}
        reason={focus.selected_reason}
        mission={mission.behavior}
        missionAnchor="call-mission"
      />
      <Panel
        title="Why this is the focus for this call"
        sub={
          evidence.length
            ? `${evidence.length} moment${evidence.length === 1 ? "" : "s"}`
            : undefined
        }
      >
        {evidence.length ? (
          <MomentList
            evidence={evidence}
            showCall={false}
            label="Moments from this call"
            fictional={coaching.sandbox}
          />
        ) : (
          <div className={styles.body}>
            <p className={styles.momentNote}>
              This report kept no timestamp for this suggestion.{" "}
              <Link href={report.href}>Open the report</Link> to read it in
              context.
            </p>
          </div>
        )}
      </Panel>
      <LessonPanel
        lesson={lesson}
        clips={coaching.media_clips}
        fallbackObservation={focus.explanation}
        strength={coaching.strength}
      />
      <aside className={styles.conversationRail} aria-label="Your next call">
        <MissionPanel
          id="call-mission"
          mission={mission}
          practice={practice}
          foot="One call gives a suggestion, not a pattern; My coaching follows your calls."
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
            <Row
              icon={<GraduationCap size={15} aria-hidden="true" />}
              title="My coaching across calls"
              href="/coaching"
            />
          </List>
        </Panel>
      </aside>
    </div>
  );
}
