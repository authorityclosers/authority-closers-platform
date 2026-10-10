"use client";

import Link from "next/link";
import { FileSearch } from "lucide-react";
import { Empty, Panel } from "../ui/kit";
import type { CallCoaching } from "./coaching-read";
import { EvidencePlayer } from "./evidence-player";
import styles from "./coaching.module.css";

export function CallCoachingStory({ coaching }: { coaching: CallCoaching }) {
  const { focus, lesson, mission, practice, evidence } = coaching;
  if (!focus || !lesson || !mission || !practice)
    return (
      <Empty
        icon={FileSearch}
        title="This call's coaching is unavailable"
        text="Open the call for its available report and analysis status."
        action={{
          href: `/analysis/calls/${coaching.submission_id}`,
          label: "Open call",
        }}
      />
    );
  return (
    <div className={styles.story}>
      <Panel title="What You Should Work On Now">
        <div className={styles.panelBody}>
          <div className={styles.meta}>
            <span>One focus for this call</span>
            <span>
              {coaching.basis === "general_practice"
                ? "General practice"
                : "Call recommendation"}
            </span>
          </div>
          <h3>{focus.label}</h3>
          <p>{focus.explanation}</p>
          <p>
            <strong>Why it matters</strong>
            {focus.why_it_matters}
          </p>
          <a href="#call-mission" className={styles.button}>
            Your next-call mission
          </a>
        </div>
      </Panel>
      <Panel title="Why this is the focus for this call">
        <div className={styles.panelBody}>
          <p>{focus.selected_reason}</p>
          {evidence[0] ? (
            <EvidencePlayer evidence={evidence[0]} />
          ) : (
            <p className={styles.muted}>
              This report has no retained timestamp for this suggestion. Open
              the report to inspect its context.
            </p>
          )}
          {evidence.length > 1 ? (
            <details className={styles.disclosure}>
              <summary>More moments from this call</summary>
              {evidence.slice(1).map((m) => (
                <EvidencePlayer key={m.segment_id + m.start_ms} evidence={m} />
              ))}
            </details>
          ) : null}
        </div>
      </Panel>
      <Panel title="Here’s What Better Looks Like">
        <div className={styles.panelBody}>
          <h3>{lesson.title}</h3>
          <p>{lesson.quick_idea}</p>
          <ol className={styles.framework}>
            {lesson.framework.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <p>
            <strong>Your call</strong>
            {lesson.own_call?.observation ?? focus.explanation}
          </p>
          <p>
            <strong>Better direction</strong>
            {lesson.better_direction}
          </p>
          <details className={styles.disclosure}>
            <summary>Read the structured text lesson</summary>
            <h4>Why this matters</h4>
            <p>{lesson.why_it_matters}</p>
            <h4>What good looks like</h4>
            <p>{lesson.good_looks_like}</p>
            {lesson.example_wording.length ? (
              <>
                <h4>Optional wording</h4>
                <ul>
                  {lesson.example_wording.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </>
            ) : null}
            <h4>When to use it</h4>
            <p>{lesson.when_to_use}</p>
            <h4>When to use another approach</h4>
            <p>{lesson.when_not}</p>
            <ul>
              {lesson.checklist.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <p className={styles.muted}>{lesson.source}</p>
          </details>
        </div>
      </Panel>
      <div id="call-mission">
        <Panel title="Try This on Your Next Call">
          <div className={styles.panelBody}>
            <h3>One practice</h3>
            <p>{practice.exercise}</p>
            <p>
              <strong>Check your practice</strong>
              {practice.success_condition}
            </p>
            <div className={styles.mission}>
              <h3>Your next-call mission</h3>
              <p>{mission.behavior}</p>
              <p>
                <strong>Use it when</strong>
                {mission.context}
              </p>
              <p>
                <strong>Done when</strong>
                {mission.done_when}
              </p>
              <p className={styles.verdict}>{mission.cue}</p>
            </div>
          </div>
        </Panel>
      </div>
      <p className={styles.muted}>
        This suggestion belongs to this call.{" "}
        <Link href="/coaching">My coaching</Link> keeps your focus across calls.
      </p>
    </div>
  );
}
