"use client";

import { ChevronDown, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { callHref, UUID } from "../acquisition-client";
import { unnamedCallName } from "../call-label";
import { callDate } from "../call-status";
import styles from "./organisation.module.css";
import {
  tallyPatterns,
  useTeamPatterns,
  type PatternCall,
  type ReportPattern,
} from "./team-patterns";

/** Newest reports first; a long month reads the latest 24. */
const REPORTS_READ = 24;
const SKILLS_SHOWN = 4;
const FIX_SHOWN = 4;

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (
    parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)
  ).toUpperCase();
}

const share = (part: number, whole: number) =>
  `${whole > 0 ? Math.round((part / whole) * 100) : 0}%`;

/**
 * What keeps coming up across the team's reports (AUT-1679): how calls
 * ended, which sales skills reports most often found only partly, and each
 * report's "fix first" line. Owners and admins only; counts, never scores.
 */
export function TeamPatternsSection({
  calls,
}: {
  calls: (PatternCall & { hasReport: boolean })[];
}) {
  const reported = useMemo(
    () =>
      calls
        .filter((call) => call.hasReport && UUID.test(call.id))
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
        .slice(0, REPORTS_READ),
    [calls],
  );
  const { reads, retry } = useTeamPatterns(reported.map((call) => call.id));
  const [allSkills, setAllSkills] = useState(false);

  if (reported.length === 0)
    return (
      <p className={styles.quietLine}>
        What keeps coming up across the team&apos;s calls shows here once
        reports are ready.
      </p>
    );

  const settled = reported.every((call) => reads.has(call.id));
  const counted: { call: PatternCall; pattern: ReportPattern }[] = [];
  let failed = 0;
  let denied = 0;
  for (const call of reported) {
    const read = reads.get(call.id);
    if (read?.status === "ready" && read.pattern)
      counted.push({ call, pattern: read.pattern });
    if (read?.status === "error") failed += 1;
    if (read?.status === "denied") denied += 1;
  }
  const patterns = tallyPatterns(counted);
  const topOutcome = Math.max(1, ...patterns.outcomes.map((row) => row.calls));
  const skills = patterns.skills.filter((skill) => skill.gaps > 0);
  const shownSkills = allSkills ? skills : skills.slice(0, SKILLS_SHOWN);

  return (
    <section className={styles.section} aria-labelledby="org-patterns">
      <div className={styles.sectionHead}>
        <h2 id="org-patterns">What keeps coming up</h2>
        <span>
          {settled
            ? `From ${patterns.reports} ${patterns.reports === 1 ? "report" : "reports"} in the last 30 days`
            : "Reading the team's reports…"}
        </span>
      </div>
      <div className={`${styles.surface} ${styles.patternSurface}`}>
        {!settled ? (
          <div
            className={styles.patterns}
            role="status"
            aria-busy="true"
            aria-label="Loading reports"
          >
            {[0, 1, 2].map((column) => (
              <div key={column} className={styles.patternColumn}>
                <i className={`${styles.bone} ${styles.patternBoneTitle}`} />
                {/* The same rows as the ready panel, so nothing moves. */}
                {[0, 1, 2, 3].map((row) => (
                  <i
                    key={row}
                    className={`${styles.bone} ${styles.patternBone}`}
                    data-fix={column === 2 ? "" : undefined}
                  />
                ))}
              </div>
            ))}
          </div>
        ) : patterns.reports === 0 ? (
          <div className={styles.empty}>
            <b>
              {failed > 0
                ? "The team's reports could not be read"
                : denied > 0
                  ? "Teammates' reports can't be opened from here yet"
                  : "These reports have nothing to count yet"}
            </b>
            <p>The rest of this page is up to date.</p>
            {failed > 0 ? (
              <button
                type="button"
                className={styles.secondary}
                onClick={retry}
              >
                <RefreshCw size={14} aria-hidden="true" />
                Try again
              </button>
            ) : null}
          </div>
        ) : (
          <div className={styles.patterns}>
            <div className={styles.patternColumn}>
              <h3>How calls ended</h3>
              {patterns.outcomes.length ? (
                <ul className={styles.barList}>
                  {patterns.outcomes.map((row) => (
                    <li key={row.kind}>
                      <i
                        aria-hidden="true"
                        style={{ width: share(row.calls, topOutcome) }}
                      />
                      <span>{row.label}</span>
                      <b
                        aria-label={`${row.calls} of ${patterns.reports} calls`}
                      >
                        {row.calls}
                      </b>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={styles.patternQuiet}>
                  These reports don&apos;t record an outcome.
                </p>
              )}
            </div>

            <div className={styles.patternColumn}>
              <h3>Skills often only partly seen</h3>
              {skills.length ? (
                <>
                  <ul className={styles.barList}>
                    {shownSkills.map((skill) => (
                      <li
                        key={skill.id}
                        title={`Partly seen or needing more evidence in ${skill.gaps} of ${skill.assessed} calls`}
                      >
                        <i
                          aria-hidden="true"
                          style={{ width: share(skill.gaps, skill.assessed) }}
                        />
                        <span>{skill.label}</span>
                        <b
                          aria-label={`${skill.gaps} of ${skill.assessed} calls`}
                        >
                          {skill.gaps}
                          <small> of {skill.assessed}</small>
                        </b>
                      </li>
                    ))}
                  </ul>
                  {skills.length > SKILLS_SHOWN ? (
                    <button
                      type="button"
                      className={styles.moreToggle}
                      aria-expanded={allSkills}
                      onClick={() => setAllSkills((open) => !open)}
                    >
                      {allSkills
                        ? "Show fewer"
                        : `${skills.length - SKILLS_SHOWN} more ${skills.length - SKILLS_SHOWN === 1 ? "skill" : "skills"}`}
                      <ChevronDown
                        size={14}
                        aria-hidden="true"
                        data-open={allSkills ? "" : undefined}
                      />
                    </button>
                  ) : null}
                </>
              ) : (
                <p className={styles.patternQuiet}>
                  Every assessed skill had evidence in these reports.
                </p>
              )}
            </div>

            <div className={styles.patternColumn}>
              <h3>Fix first, in each report&apos;s words</h3>
              {patterns.fixFirst.length ? (
                <ul className={styles.fixList}>
                  {patterns.fixFirst
                    .slice(0, FIX_SHOWN)
                    .map(({ call, text }) => {
                      const owner = call.ownerName ?? "Unnamed member";
                      return (
                        <li key={call.id}>
                          <Link href={callHref(call.id)}>
                            <span className={styles.fixText}>{text}</span>
                            <span className={styles.fixMeta}>
                              <i className={styles.avatar} aria-hidden="true">
                                {initials(owner)}
                              </i>
                              <span>{owner}</span>
                              <span aria-hidden="true">·</span>
                              <span className={styles.fixCall}>
                                {call.label ?? unnamedCallName(call.createdAt)}
                              </span>
                              <span aria-hidden="true">·</span>
                              <span>{callDate(call.createdAt)}</span>
                            </span>
                          </Link>
                        </li>
                      );
                    })}
                </ul>
              ) : (
                <p className={styles.patternQuiet}>
                  These reports don&apos;t name a first fix.
                </p>
              )}
            </div>
          </div>
        )}
        {!settled || patterns.reports > 0 ? (
          <p className={styles.footnote}>
            Counts the labels each report gave; reports are drafts, not scores.
            {failed > 0 ? (
              <>
                {" "}
                {failed} {failed === 1 ? "report" : "reports"} could not be
                read.{" "}
                <button
                  type="button"
                  className={styles.inlineAction}
                  onClick={retry}
                >
                  Try again
                </button>
              </>
            ) : null}
          </p>
        ) : null}
      </div>
    </section>
  );
}
