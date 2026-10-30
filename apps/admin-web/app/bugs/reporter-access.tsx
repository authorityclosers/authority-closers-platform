"use client";

/**
 * Who may use the advanced bug reporter (owner, 31 Oct 2026): people who
 * asked wait here; the owner lets them in or turns them down, and can take it
 * away later. Each choice adds to the history; nothing is overwritten.
 * POST /v1/admin/bugs/reporter-access/{person}.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { when } from "../calls/call-data";
import { send } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import {
  ACCESS_LABEL,
  type AccessState,
  type ReporterAccessPerson,
} from "./bugs-data";
import styles from "./bugs.module.css";

type Decision = Exclude<AccessState, "requested">;

const CHOICES: Record<AccessState, { decision: Decision; label: string }[]> = {
  requested: [
    { decision: "granted", label: "Let in" },
    { decision: "denied", label: "Turn down" },
  ],
  granted: [{ decision: "revoked", label: "Take away" }],
  denied: [{ decision: "granted", label: "Let in" }],
  revoked: [{ decision: "granted", label: "Let in" }],
};

export function ReporterAccess({ people }: { people: ReporterAccessPerson[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const decide = async (person: ReporterAccessPerson, decision: Decision) => {
    if (busy) return;
    setBusy(person.personId);
    setProblem(null);
    const result = await send(
      "POST",
      `/v1/admin/bugs/reporter-access/${person.personId}`,
      { decision },
      null,
    );
    setBusy(null);
    if (!result.ok) {
      setProblem(result.message);
      return;
    }
    router.refresh();
  };

  return (
    <div className={styles.access}>
      <ul className={styles.accessList}>
        {people.map((person) => (
          <li key={person.personId} className={styles.accessRow}>
            <span className={styles.accessWho}>
              <strong>{person.name ?? person.email ?? "Someone"}</strong>
              <small className={kitStyles.muted}>
                {[
                  person.email,
                  ACCESS_LABEL[person.state],
                  person.since ? when(person.since) : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </span>
            <span className={styles.actionRow}>
              {CHOICES[person.state].map((choice, index) => (
                <button
                  key={choice.decision}
                  type="button"
                  className={kitStyles.button}
                  data-variant={
                    index === 0 && person.state === "requested"
                      ? "primary"
                      : undefined
                  }
                  disabled={busy !== null}
                  onClick={() => void decide(person, choice.decision)}
                >
                  {choice.label}
                </button>
              ))}
            </span>
          </li>
        ))}
      </ul>
      {problem ? (
        <small className={kitStyles.fieldError} role="alert">
          {problem}
        </small>
      ) : null}
    </div>
  );
}
