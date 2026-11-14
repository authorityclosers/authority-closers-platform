"use client";

/**
 * Analysis time, in Settings for everyone (orchestrator, 13 Nov 2026: the owner
 * found "no good UI which makes it understandable" how much analysis time
 * someone has): what is left, read from the same numbers the server admits an
 * analysis by, and who can add more. An organisation's owner or admin also sees
 * what each member used of the shared time. Time only, never a price.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import type { Allowance } from "../acquisition-client";
import { analysisTimeLeft, formatAnalysisTime } from "../analysis-time";
import { readAllowance } from "../dashboard/dashboard-data";
import { displayName } from "../display-name";
import { useCanHere } from "../workspace-role";
import styles from "./analysis-time.module.css";

type Read =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; allowance: Allowance };

export type MemberTime = {
  person_id: string;
  name: string;
  used_seconds: number;
};

/** The big line: what is left, or why there is nothing to count. */
export function analysisTimeHeadline(allowance: Allowance): string {
  if (allowance.unlimited) return "Unlimited";
  if (allowance.allowance_seconds <= 0 && allowance.committed_seconds <= 0)
    return "Not on yet";
  return analysisTimeLeft(allowance, "member") ?? "None left";
}

/** Each member's use of the organisation's time, for its owner or admins; null otherwise. */
export async function readTeamTime(
  signal: AbortSignal,
): Promise<MemberTime[] | null> {
  const response = await fetch("/v1/me/analysis-time/team", {
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  if (!response.ok) return null;
  const body: unknown = await response.json();
  const people =
    body &&
    typeof body === "object" &&
    Array.isArray((body as { people?: unknown }).people)
      ? (body as { people: unknown[] }).people
      : [];
  return people.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const row = item as Record<string, unknown>;
    return typeof row.person_id === "string" &&
      typeof row.name === "string" &&
      typeof row.used_seconds === "number" &&
      row.used_seconds >= 0
      ? [
          {
            person_id: row.person_id,
            name: row.name,
            used_seconds: row.used_seconds,
          },
        ]
      : [];
  });
}

export function AnalysisTimeSection() {
  const [read, setRead] = useState<Read>({ status: "loading" });
  const [team, setTeam] = useState<MemberTime[] | null>(null);
  const canHere = useCanHere();
  const pays = canHere("billing.view");
  useEffect(() => {
    const controller = new AbortController();
    readAllowance(controller.signal).then(
      (allowance) => setRead({ status: "ready", allowance }),
      () => {
        if (!controller.signal.aborted) setRead({ status: "error" });
      },
    );
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!pays) return;
    const controller = new AbortController();
    readTeamTime(controller.signal).then(setTeam, () => undefined);
    return () => controller.abort();
  }, [pays]);
  const shared = team !== null && team.length > 0;
  return (
    <div className={styles.stack}>
      <section
        className={styles.card}
        aria-label="Analysis time"
        aria-busy={read.status === "loading"}
      >
        {shared ? <p className={styles.who}>Your workspace</p> : null}
        <p className={styles.left} role="status">
          {read.status === "loading"
            ? "Checking…"
            : read.status === "error"
              ? "Couldn't check right now"
              : analysisTimeHeadline(read.allowance)}
        </p>
        <p className={styles.who}>
          {pays === null ? null : pays ? (
            <>
              Add more in{" "}
              <Link href="/settings/plan" className={styles.link}>
                Plan &amp; usage
              </Link>
              .
            </>
          ) : (
            "Your owner or admin can add more."
          )}
        </p>
      </section>
      {shared ? (
        <section
          className={styles.card}
          aria-label="Each seller's analysis time"
        >
          <p className={styles.title}>Each seller</p>
          <p className={styles.who}>What each one used of the shared time</p>
          <ul className={styles.people}>
            {team.map((person) => (
              <li key={person.person_id}>
                <span className={styles.name}>{displayName(person.name)}</span>
                <span className={styles.used}>
                  {person.used_seconds > 0
                    ? `${formatAnalysisTime(person.used_seconds)} used`
                    : "None used"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
